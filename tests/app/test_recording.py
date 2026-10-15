"""The run recorder — the missing half of the cost rule.

The bug these tests pin down: `cost_ledger` was empty after weeks of live runs, because
`record_call` had no caller outside its own module. `BudgetGuard` enforces the monthly
ceiling against the ledger, so an empty ledger meant every run compared its spend to zero
and passed. The guard was not lenient, it was blind.

So the test that matters most is not "a row is written" but `test_ceiling_now_sees_a_run`:
spend recorded through this module is spend the guard can refuse.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.costs.ledger import spend_this_month, spend_total
from app.models import CostLedger, Generation, Keyframe, Persona, Shot, VoiceLine
from app.pipeline.recording import ShotSpec, open_run

from .conftest import requires_db

pytestmark = requires_db

VERIFIED = dt.date(2026, 10, 15)

SHOTS = [
    ShotSpec(
        name="setup",
        description="she talks to camera in a bunker",
        duration_s=5.0,
        face_expected=True,
        dialogue="pin's just over the lip",
    ),
    ShotSpec(
        name="result",
        description="the ball rolls back down the sand",
        duration_s=5.0,
        face_expected=False,
    ),
]


def _run(session: Session, **kwargs: object):
    return open_run(
        session,
        persona_name="Recorder Test",
        brief="bunker flop",
        video_format="reaction",
        shots=SHOTS,
        **kwargs,  # type: ignore[arg-type]
    )


def test_open_run_writes_the_shot_list(session: Session) -> None:
    recorder = _run(session)
    assert sorted(recorder.shots) == ["result", "setup"]

    rows = session.execute(
        select(Shot).where(Shot.content_piece_id == recorder.piece.id).order_by(Shot.order_index)
    ).scalars()
    kinds = [(r.order_index, r.shot_type, r.dialogue is not None) for r in rows]
    assert kinds == [(0, "face", True), (1, "broll", False)]


def test_the_same_persona_is_reused(session: Session) -> None:
    """`persona.name` is unique, and two Mollies would split her history in two."""
    first = _run(session)
    second = _run(session)
    assert first.piece.persona_id == second.piece.persona_id
    count = session.execute(
        select(func.count()).select_from(Persona).where(Persona.name == "Recorder Test")
    ).scalar_one()
    assert count == 1


def test_keyframe_writes_its_ledger_row(session: Session) -> None:
    recorder = _run(session)
    frame = recorder.keyframe(
        "setup",
        provider="fal",
        model="fal-ai/nano-banana-2/edit",
        prompt="she stands in a greenside bunker",
        storage_key="persona/x/keyframe/setup.png",
        identity_score=0.981,
        units=Decimal(1),
        unit_price=Decimal("0.07"),
        price_verified_on=VERIFIED,
    )
    row = session.execute(select(CostLedger).where(CostLedger.ref_id == frame.id)).scalar_one()
    assert row.ref_table == "keyframe"
    assert row.total_usd == Decimal("0.070000")
    assert row.price_verified_on == VERIFIED


def test_take_sets_the_cost_column_and_the_ledger_row(session: Session) -> None:
    """Both writes, or the total does not match the piece it belongs to."""
    recorder = _run(session)
    take = recorder.take(
        "setup",
        keyframe=None,
        provider="fal",
        model="minimax/h3-max-turbo/image-to-video",
        prompt="she talks to camera",
        params={"resolution": "1080P"},
        duration_s=5.0,
        units=Decimal(5),
        unit_price=Decimal("0.08"),
        price_verified_on=VERIFIED,
        identity_min=0.971,
        identity_mean=0.984,
    )
    assert take.cost_usd == Decimal("0.400000")
    row = session.execute(select(CostLedger).where(CostLedger.ref_id == take.id)).scalar_one()
    assert (row.ref_table, row.total_usd) == ("generation", Decimal("0.400000"))


def test_rejected_takes_are_recorded_too(session: Session) -> None:
    """A take that was generated and not used still cost what it cost."""
    recorder = _run(session)
    for status in ("scored", "auto_rejected", "auto_rejected"):
        recorder.take(
            "setup",
            keyframe=None,
            provider="fal",
            model="m",
            prompt="p",
            params={},
            duration_s=5.0,
            units=Decimal(5),
            unit_price=Decimal("0.08"),
            price_verified_on=VERIFIED,
            status=status,
        )
    takes = session.execute(select(func.count()).select_from(Generation)).scalar_one()
    assert takes == 3
    assert spend_total(session) == Decimal("1.200000")


def test_voice_line_carries_its_cost(session: Session) -> None:
    recorder = _run(session)
    line = recorder.voice(
        "setup",
        text="pin's just over the lip",
        voice_id="voice-1",
        provider="fal",
        storage_key="persona/x/voice/setup.mp3",
        units=Decimal("0.023"),
        unit_price=Decimal("30"),
        price_verified_on=VERIFIED,
    )
    assert line.cost_usd == Decimal("0.690000")
    row = session.execute(select(CostLedger).where(CostLedger.ref_id == line.id)).scalar_one()
    assert row.ref_table == "voice_line"


def test_a_call_for_an_unopened_shot_refuses(session: Session) -> None:
    """Rather than silently hanging the ledger row off whatever shot came first."""
    recorder = _run(session)
    with pytest.raises(KeyError, match="no shot named 'facepalm'"):
        recorder.voice(
            "facepalm",
            text="they did not",
            voice_id="v",
            provider="fal",
            storage_key="k",
            units=Decimal(1),
            unit_price=Decimal(1),
            price_verified_on=None,
        )


def test_ceiling_now_sees_a_run(session: Session) -> None:
    """The regression that matters: the guard reads the ledger, so the ledger must fill.

    Before this module the answer here was always Decimal(0), whatever had been spent.
    """
    assert spend_this_month(session, dt.datetime.now(dt.UTC)) == Decimal(0)
    recorder = _run(session)
    recorder.keyframe(
        "setup",
        provider="fal",
        model="m",
        prompt="p",
        storage_key="k",
        identity_score=None,
        units=Decimal(1),
        unit_price=Decimal("0.07"),
        price_verified_on=VERIFIED,
    )
    recorder.take(
        "result",
        keyframe=None,
        provider="fal",
        model="m",
        prompt="p",
        params={},
        duration_s=5.0,
        units=Decimal(5),
        unit_price=Decimal("0.08"),
        price_verified_on=VERIFIED,
    )
    assert spend_this_month(session, dt.datetime.now(dt.UTC)) == Decimal("0.470000")


def test_finish_closes_the_piece(session: Session) -> None:
    recorder = _run(session)
    recorder.finish()
    assert recorder.piece.status == "assembled"
    assert recorder.piece.render_completed_at is not None
    assert recorder.piece.brief_started_at is not None
    assert recorder.piece.render_completed_at >= recorder.piece.brief_started_at


def test_nothing_is_left_uncommitted(session: Session) -> None:
    """Each paid call commits its own pair, so a crash cannot lose billed spend."""
    recorder = _run(session)
    recorder.keyframe(
        "setup",
        provider="fal",
        model="m",
        prompt="p",
        storage_key="k",
        identity_score=None,
        units=Decimal(1),
        unit_price=Decimal("0.07"),
        price_verified_on=VERIFIED,
    )
    session.rollback()
    assert session.execute(select(func.count()).select_from(Keyframe)).scalar_one() == 1
    assert session.execute(select(func.count()).select_from(CostLedger)).scalar_one() == 1
    assert session.execute(select(func.count()).select_from(VoiceLine)).scalar_one() == 0
