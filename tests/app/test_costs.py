"""Task 0.7 — the cost ledger and the budget guard.

CLAUDE.md makes two demands and they are tested separately because they fail
differently: every paid call goes through the guard, and every paid call writes a
ledger row in the same transaction. A cost column committed without its ledger row is
spend nobody can audit; a ledger row without the column is a total that does not match
the piece it belongs to.

D8's ceilings are deliberately unset (owner, 2026-09-29: run it first, set a ceiling
from real numbers), so observe mode gets as much attention as enforce mode. The thing
worth proving is that observe mode is not "no guard" — a stale price and a missing
run budget still refuse.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import BudgetConfig, load_all
from app.config.schema import BudgetSettings, ProviderSlot
from app.costs import (
    BudgetExceeded,
    BudgetGuard,
    BudgetNotSet,
    record_call,
    record_failed_call,
    record_generation_cost,
    spend_for_piece,
    spend_this_month,
    spend_total,
)
from app.models import CostLedger, Generation, Job

from .conftest import requires_db

pytestmark = requires_db

REAL = load_all()


def _guard(**budget: object) -> BudgetGuard:
    settings = BudgetSettings(**budget)  # type: ignore[arg-type]
    return BudgetGuard(BudgetConfig(budget=settings), REAL.providers)


def _generation(session: Session, persona_id: str) -> Generation:
    piece: uuid.UUID = session.execute(
        text(
            "INSERT INTO content_piece (persona_id, brief, format) "
            "VALUES (:p, 'b', 'reaction') RETURNING id"
        ),
        {"p": persona_id},
    ).scalar_one()
    shot: uuid.UUID = session.execute(
        text(
            "INSERT INTO shot (content_piece_id, order_index, description, duration_s, shot_type) "
            "VALUES (:c, 1, 'd', 5, 'face') RETURNING id"
        ),
        {"c": piece},
    ).scalar_one()
    generation = Generation(
        shot_id=shot,
        provider="fal",
        model="minimax/h3-max-turbo/image-to-video",
        prompt="p",
        duration_s=5.0,
        cost_usd=Decimal("0"),
    )
    session.add(generation)
    session.flush()
    return generation


# ------------------------------------------------------------------- pricing --
def test_the_guard_prices_from_config_not_from_code() -> None:
    """CLAUDE.md keeps prices in config. A price in code is a second source of truth."""
    guard = _guard(mode="observe")
    slot, unit_price, unit = guard.price("video", "golf")
    assert slot.model == "minimax/h3-max-turbo/image-to-video"
    assert unit == "second"
    # 768P, post-discount, verified 2026-10-01. See ADR 0013: this was 0.0125 — the 480p
    # LAUNCH-DISCOUNT rate — on a slot sending resolution 768P.
    assert unit_price == Decimal("0.04")
    assert slot.price_basis == {"resolution": "768P"}, (
        "the price must say which resolution it is for, or it is not a price"
    )


def test_a_five_second_take_costs_what_the_provider_charges() -> None:
    """Was `..._costs_what_the_spike_measured`, asserting $0.0625.

    The spike measured a real number against the wrong resolution tier, and this test
    pinned it, so the error had a passing test guarding it. A take is $0.20: five seconds
    at the 768P rate of $0.04. Renamed because what the spike measured is not the
    authority — what the provider charges is.
    """
    assert _guard(mode="observe").estimate("video", "golf", Decimal("5")) == Decimal("0.200000")


def test_an_unpriced_slot_cannot_be_billed_against() -> None:
    guard = _guard(mode="observe")
    with pytest.raises(Exception, match=r"no price set|placeholder"):
        guard.price("llm", "shotlist")


def test_a_stale_price_is_refused_even_in_observe_mode() -> None:
    """Observe mode defers ONE of the three refusals. Not this one.

    A guard reserving against a price verified a year ago is a guard that understates,
    and understating is the direction that lets a run sail past a cap while reporting
    it is inside one.
    """
    guard = _guard(mode="observe")
    with pytest.raises(Exception, match="days ago"):
        guard.price("video", "golf", today=dt.date(2027, 6, 1))


def test_a_slot_pricing_in_two_units_is_refused() -> None:
    """The guard cannot guess which unit bills."""
    guard = _guard(mode="observe")
    ambiguous = ProviderSlot(
        backend="fal",
        model="m",
        verified_on=dt.date(2026, 9, 25),
        price_usd_per_second=Decimal("0.01"),
        price_usd_per_image=Decimal("0.08"),
    )
    guard._providers.providers["video"]["ambiguous"] = ambiguous  # type: ignore[index]
    try:
        with pytest.raises(ValueError, match="cannot tell which unit"):
            guard.price("video", "ambiguous")
    finally:
        del guard._providers.providers["video"]["ambiguous"]


# ------------------------------------------- [A7] a run needs an explicit budget --
def test_a_run_without_a_budget_is_refused() -> None:
    """Amendment A7, and the thing actually bounding spend while ceilings are unset."""
    with pytest.raises(BudgetNotSet, match="only thing bounding spend"):
        _guard(mode="observe").require_run_budget(None)


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-5")])
def test_a_nonsense_run_budget_is_refused(amount: Decimal) -> None:
    with pytest.raises(BudgetNotSet, match="must be positive"):
        _guard(mode="observe").require_run_budget(amount)


def test_a_real_run_budget_is_accepted() -> None:
    assert _guard(mode="observe").require_run_budget(Decimal("25")) == Decimal("25")


# ---------------------------------------------------- the ledger, same transaction --
def test_a_generations_cost_and_its_ledger_row_are_written_together(
    session: Session, persona_id: str
) -> None:
    """CLAUDE.md's same-transaction rule. There is no function that does one alone."""
    generation = _generation(session, persona_id)
    row = record_generation_cost(
        session,
        generation,
        units=Decimal("5"),
        unit_price=Decimal("0.0125"),
        price_verified_on=dt.date(2026, 9, 25),
    )
    assert row.total_usd == Decimal("0.062500")
    assert generation.cost_usd == row.total_usd
    assert row.ref_table == "generation"
    assert row.ref_id == generation.id


def test_a_rollback_loses_the_cost_and_the_row_together(session: Session, persona_id: str) -> None:
    """The property the same-transaction rule buys: they cannot disagree.

    If they committed separately, a crash between them would leave a generation with
    a cost nothing accounts for, or a ledger total nothing produced.
    """
    generation = _generation(session, persona_id)
    savepoint = session.begin_nested()
    record_generation_cost(
        session,
        generation,
        units=Decimal("5"),
        unit_price=Decimal("0.0125"),
        price_verified_on=None,
    )
    assert session.execute(select(CostLedger)).scalars().all()
    savepoint.rollback()
    assert session.execute(select(CostLedger)).scalars().all() == []


def test_the_ledger_records_the_date_of_the_price_it_charged(
    session: Session, persona_id: str
) -> None:
    """So a reconciliation against a real invoice can find the stale ones."""
    generation = _generation(session, persona_id)
    row = record_generation_cost(
        session,
        generation,
        units=Decimal("5"),
        unit_price=Decimal("0.0125"),
        price_verified_on=dt.date(2026, 9, 25),
    )
    assert row.price_verified_on == dt.date(2026, 9, 25)


def test_an_unknown_reference_table_is_refused(session: Session) -> None:
    with pytest.raises(ValueError, match="ref_table must be one of"):
        record_call(
            session,
            ref_table="invoice",
            ref_id=uuid.uuid4(),
            provider="fal",
            units=Decimal("1"),
            unit_price=Decimal("1"),
            price_verified_on=None,
        )


# ------------------------------------------- [A2] a call that produced nothing --
def test_a_call_that_produced_nothing_still_lands_in_the_ledger(session: Session) -> None:
    """Amendment A2. A timeout after billing has no generation row to hang a cost on,
    and that spend used to have nowhere to live."""
    # In flight, so no cost yet — which is what the nullable column is for.
    job = Job(provider="fal", status="running")
    session.add(job)
    session.flush()
    assert job.cost_usd is None

    row = record_failed_call(
        session,
        job,
        status="timed_out",
        units=Decimal("5"),
        unit_price=Decimal("0.0125"),
        price_verified_on=dt.date(2026, 9, 25),
    )
    assert row.ref_table == "job"
    assert job.status == "timed_out"
    assert job.completed_at is not None
    assert job.cost_usd == row.total_usd == Decimal("0.062500")
    assert spend_total(session) == Decimal("0.062500")


def test_finishing_a_call_sets_its_status_and_cost_together(session: Session) -> None:
    """`ck_job_finished_has_cost` refuses a finished job with no cost.

    So a ledger function that set only the cost could not be called on a row already
    marked finished — which is how the constraint found the first version of this
    signature, before it took a status at all.
    """
    job = Job(provider="fal", status="running")
    session.add(job)
    session.flush()
    with pytest.raises(ValueError, match="record_generation_cost"):
        record_failed_call(
            session,
            job,
            status="succeeded",
            units=Decimal("1"),
            unit_price=Decimal("1"),
            price_verified_on=None,
        )


def test_per_piece_spend_counts_the_takes_that_failed_after_billing(
    session: Session, persona_id: str
) -> None:
    """Otherwise per-piece cost understates exactly the spend a ceiling exists to catch."""
    generation = _generation(session, persona_id)
    piece_id: uuid.UUID = session.execute(
        text("SELECT content_piece_id FROM shot WHERE id = :s"), {"s": generation.shot_id}
    ).scalar_one()

    record_generation_cost(
        session,
        generation,
        units=Decimal("5"),
        unit_price=Decimal("0.0125"),
        price_verified_on=None,
    )
    failed = Job(provider="fal", status="running", generation_id=generation.id)
    session.add(failed)
    session.flush()
    record_failed_call(
        session,
        failed,
        status="timed_out",
        units=Decimal("5"),
        unit_price=Decimal("0.0125"),
        price_verified_on=None,
    )

    assert spend_for_piece(session, piece_id) == Decimal("0.125000")


def test_spend_this_month_ignores_last_month(session: Session, persona_id: str) -> None:
    generation = _generation(session, persona_id)
    record_generation_cost(
        session, generation, units=Decimal("5"), unit_price=Decimal("1"), price_verified_on=None
    )
    session.execute(text("UPDATE cost_ledger SET created_at = now() - interval '45 days'"))
    assert spend_this_month(session) == Decimal("0")
    assert spend_total(session) == Decimal("5.000000")


# ------------------------------------------------------------- observe mode --
def test_observe_mode_reports_a_breach_rather_than_refusing(
    session: Session, persona_id: str
) -> None:
    """The owner's decision of 2026-09-29, and the point of it.

    Observing produces no observation unless a call that WOULD have been refused is
    still visible, so the reservation carries the number to put in front of a human.
    """
    generation = _generation(session, persona_id)
    record_generation_cost(
        session, generation, units=Decimal("100"), unit_price=Decimal("1"), price_verified_on=None
    )

    guard = _guard(mode="observe", monthly_usd=Decimal("50"))
    reservation = guard.check(session, estimated_usd=Decimal("10"))

    assert reservation.observed_breach
    assert reservation.would_have_refused is not None
    assert "monthly ceiling" in reservation.would_have_refused
    assert reservation.month_to_date == Decimal("100.000000")


def test_observe_mode_with_no_ceiling_at_all_permits_and_reports(
    session: Session, persona_id: str
) -> None:
    """Observe mode with no ceiling at all: nothing set, so nothing to breach.

    Constructed rather than read from the real config, which enforced $100 on 2026-10-01.
    The behaviour is still worth a test — it is what any project runs before it has a
    month of spend to set a ceiling from — but it is no longer this repository's state.
    """
    guard = BudgetGuard(BudgetConfig(budget=BudgetSettings(mode="observe")), REAL.providers)
    reservation = guard.check(session, estimated_usd=Decimal("1000"))
    assert not reservation.observed_breach
    assert reservation.warning is None


def test_enforce_mode_refuses_before_the_call(session: Session, persona_id: str) -> None:
    """Flipping one config value starts refusing, with no other change."""
    generation = _generation(session, persona_id)
    record_generation_cost(
        session, generation, units=Decimal("100"), unit_price=Decimal("1"), price_verified_on=None
    )

    guard = _guard(mode="enforce", monthly_usd=Decimal("50"))
    with pytest.raises(BudgetExceeded, match="Refused before the call was made") as exc:
        guard.check(session, estimated_usd=Decimal("10"))
    assert exc.value.ceiling == Decimal("50")
    assert exc.value.spent == Decimal("100.000000")


def test_enforce_mode_warns_before_it_refuses(session: Session, persona_id: str) -> None:
    """A run about to fail should say so, not discover it on the last call."""
    generation = _generation(session, persona_id)
    record_generation_cost(
        session, generation, units=Decimal("85"), unit_price=Decimal("1"), price_verified_on=None
    )
    reservation = _guard(mode="enforce", monthly_usd=Decimal("100")).check(
        session, estimated_usd=Decimal("1")
    )
    assert reservation.warning is not None
    assert "80%" in reservation.warning


def test_a_per_piece_ceiling_is_enforced(session: Session, persona_id: str) -> None:
    generation = _generation(session, persona_id)
    piece_id: uuid.UUID = session.execute(
        text("SELECT content_piece_id FROM shot WHERE id = :s"), {"s": generation.shot_id}
    ).scalar_one()
    record_generation_cost(
        session, generation, units=Decimal("9"), unit_price=Decimal("1"), price_verified_on=None
    )

    guard = _guard(mode="enforce", per_piece_usd=Decimal("10"))
    with pytest.raises(BudgetExceeded, match="per-piece ceiling"):
        guard.check(session, estimated_usd=Decimal("5"), content_piece_id=piece_id)


def test_enforce_with_no_ceiling_is_refused_by_config() -> None:
    """A guard claiming to enforce against nothing quietly permits everything.

    Observe mode is the honest way to say "no ceiling yet", and this is what stops
    the dishonest way being expressible.
    """
    with pytest.raises(ValueError, match="nothing to enforce"):
        BudgetSettings(mode="enforce")


def test_the_repositorys_own_budget_enforces_the_owners_hundred_dollars() -> None:
    """Pins the owner's decision so a later change is deliberate rather than drift.

    Answered 2026-10-01 at $100/month, enforced. The first answer (2026-09-29) was "no
    ceiling yet, observe first", taken on the understanding that a take cost 6 cents; it
    costs 20, and a finished piece about $20, so $100 is roughly five pieces a month.
    """
    budget = REAL.budget.budget
    assert budget.mode == "enforce"
    assert budget.monthly_usd == Decimal("100")
    assert budget.per_piece_usd is None, (
        "deliberately unset: no piece has a measured cost yet, so a per-piece ceiling "
        "would be inventing the number it is meant to bound"
    )
    assert budget.require_explicit_budget_per_run is True, (
        "A7 was not part of what was deferred: it is the only thing bounding spend"
    )


def test_the_real_config_refuses_past_the_owners_hundred_dollars(
    session: Session, persona_id: str
) -> None:
    """D8 as behaviour, not as a stored value.

    The owner set $100/month on 2026-10-01. A ceiling that loads correctly and then
    fails to refuse is worse than no ceiling, because it is believed — the same shape
    as the gate that accepted shots it could not verify. So this exercises the real
    `config/budget.yaml` rather than a constructed one.
    """
    from app.config import load_all
    from app.costs.guard import BudgetGuard

    config = load_all(Path("config"))
    guard = BudgetGuard(config.budget, config.providers)

    generation = _generation(session, persona_id)
    record_generation_cost(
        session, generation, units=Decimal("99"), unit_price=Decimal("1"), price_verified_on=None
    )

    # $99 spent, and a single take at the corrected 768P price is $0.20.
    with pytest.raises(BudgetExceeded, match="Refused before the call was made") as exc:
        guard.check(session, estimated_usd=Decimal("2"))
    assert exc.value.ceiling == Decimal("100")


def test_the_real_config_warns_at_eighty_dollars(session: Session, persona_id: str) -> None:
    """A run about to exhaust the month should say so on the call before it does."""
    from app.config import load_all
    from app.costs.guard import BudgetGuard

    config = load_all(Path("config"))
    guard = BudgetGuard(config.budget, config.providers)

    generation = _generation(session, persona_id)
    record_generation_cost(
        session, generation, units=Decimal("79"), unit_price=Decimal("1"), price_verified_on=None
    )
    reservation = guard.check(session, estimated_usd=Decimal("2"))
    assert reservation.warning is not None
    assert "$100" in reservation.warning
