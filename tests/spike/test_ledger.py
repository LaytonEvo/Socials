"""The budget guard. These tests are the reason it can be trusted with a card."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from scripts.spike.errors import BudgetExceeded, BudgetNotSet, UnverifiedPriceError
from scripts.spike.ledger import CostLedger


def test_refusal_happens_before_the_call(ledger, priced):
    """The call must not run. A guard that refuses afterwards guards nothing."""
    called = []
    with (
        pytest.raises(BudgetExceeded, match="No call was made"),
        ledger.paid_call(priced, units=100, ref="huge"),
    ):
        called.append(1)
    assert called == []
    assert ledger.spent == Decimal("0")


def test_spend_accumulates_and_is_recorded(ledger, priced):
    for i in range(3):
        with ledger.paid_call(priced, units=5, ref=f"clip-{i}") as outcome:
            outcome.ok = True
    assert ledger.spent == Decimal("6.000000")  # 3 clips x 5s x $0.40
    assert len(ledger.entries) == 3
    assert len(ledger.log.read("cost")) == 3


def test_budget_stops_the_run_partway(ledger, priced):
    """A cap that only warns is not a cap."""
    done = 0
    with pytest.raises(BudgetExceeded):
        for i in range(10):
            with ledger.paid_call(priced, units=5, ref=f"clip-{i}") as outcome:
                outcome.ok = True
            done += 1
    assert done == 5  # $10 budget / $2 per clip
    assert ledger.spent <= ledger.budget_usd


def test_failed_calls_are_still_charged_and_recorded(ledger, priced):
    """BUILD_ORDER amendment A2: a call that times out has still been paid for."""
    with pytest.raises(RuntimeError), ledger.paid_call(priced, units=5, ref="doomed"):
        raise RuntimeError("provider 504")
    entry = ledger.entries[-1]
    assert entry["ok"] is False
    assert "provider 504" in entry["error"]
    assert Decimal(entry["total_usd"]) > 0
    assert ledger.spent == Decimal("2.000000")


def test_actual_cost_overrides_the_estimate(ledger, priced):
    with ledger.paid_call(priced, units=5, ref="short") as outcome:
        outcome.actual_usd = Decimal("0.50")
    entry = ledger.entries[-1]
    assert entry["total_usd"] == "0.50"
    assert Decimal(entry["estimate_error_usd"]) == Decimal("0.50") - Decimal("2.000000")


def test_unverified_price_cannot_be_spent_against(ledger, priced):
    import dataclasses

    stale = dataclasses.replace(priced, verified_on=dt.date(2020, 1, 1), backend="acme")
    with pytest.raises(UnverifiedPriceError), ledger.paid_call(stale, units=1, ref="x"):
        pass


def test_negative_budget_refused(run_log):
    with pytest.raises(BudgetNotSet):
        CostLedger(budget_usd=Decimal("-1"), log=run_log)


def test_zero_budget_refuses_every_paid_call(run_log, priced):
    ledger = CostLedger(budget_usd=Decimal("0"), log=run_log, today=dt.date(2026, 9, 22))
    with pytest.raises(BudgetExceeded), ledger.paid_call(priced, units=1, ref="x"):
        pass


def test_fake_spend_is_flagged(ledger, cfg):
    fake = cfg.provider("video", "fake")
    with ledger.paid_call(fake, units=5, ref="fake-clip") as outcome:
        outcome.ok = True
    assert ledger.has_fake_spend is True
    assert ledger.summary()["contains_fake_spend"] is True


def test_summary_breaks_down_by_provider(ledger, priced):
    with ledger.paid_call(priced, units=5, ref="a") as o:
        o.ok = True
    summary = ledger.summary()
    assert summary["by_provider"]["video/flagship"]["calls"] == 1
    assert summary["spent_usd"] == "2.000000"
