"""The cost ledger: every paid call, recorded where it can be reconciled.

CLAUDE.md: "Every paid API call goes through the cost guard and writes a
`cost_ledger` row in the same transaction." The same-transaction part is the whole
point — a cost column committed without its ledger row is spend nobody can audit,
and a ledger row without the column is a total that does not match the piece it
belongs to. So both writes happen in one flush, and the caller cannot do one without
the other because there is no function here that only does one.

Amendment A2's case is first-class: `record_failed_call` exists because a timeout
after billing has no `generation` row to hang a cost on, and that spend used to have
nowhere to live.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CostLedger, Generation, Job

#: Tables a ledger row may reference, matching `ck_ref_table_vocabulary`.
REF_TABLES = frozenset({"generation", "job", "keyframe", "voice_line"})


def record_call(
    session: Session,
    *,
    ref_table: str,
    ref_id: uuid.UUID,
    provider: str,
    units: Decimal,
    unit_price: Decimal,
    price_verified_on: dt.date | None,
) -> CostLedger:
    """Write one ledger row. Flushed, not committed: the caller owns the transaction.

    Deliberately not committing. The point of the same-transaction rule is that the
    cost column and this row land together, and a commit here would break that by
    making this row durable before the thing it describes.
    """
    if ref_table not in REF_TABLES:
        raise ValueError(f"ref_table must be one of {sorted(REF_TABLES)}, got {ref_table!r}")

    row = CostLedger(
        ref_table=ref_table,
        ref_id=ref_id,
        provider=provider,
        units=units,
        unit_price=unit_price,
        total_usd=(units * unit_price).quantize(Decimal("0.000001")),
        price_verified_on=price_verified_on,
    )
    session.add(row)
    session.flush()
    return row


def record_generation_cost(
    session: Session,
    generation: Generation,
    *,
    units: Decimal,
    unit_price: Decimal,
    price_verified_on: dt.date | None,
) -> CostLedger:
    """Set a generation's cost AND write its ledger row, in one flush."""
    row = record_call(
        session,
        ref_table="generation",
        ref_id=generation.id,
        provider=generation.provider,
        units=units,
        unit_price=unit_price,
        price_verified_on=price_verified_on,
    )
    generation.cost_usd = row.total_usd
    session.flush()
    return row


#: Terminal states a failed call can end in. `succeeded` is excluded because a
#: successful call has a `generation` row and goes through `record_generation_cost`.
FAILED_STATUSES = frozenset({"failed", "timed_out", "cancelled"})


def record_failed_call(
    session: Session,
    job: Job,
    *,
    status: str,
    units: Decimal,
    unit_price: Decimal,
    price_verified_on: dt.date | None,
) -> CostLedger:
    """Finish a call that produced nothing, and record what it cost — amendment A2.

    A refusal after billing, a timeout, and a mid-generation failure all cost money
    and have no `generation` row. Without this the ledger was quietly incomplete and
    the gap only showed up against an invoice.

    Sets the status as well as the cost, because the schema requires both to move
    together: `ck_job_finished_has_cost` refuses a finished job with no cost, so a
    function that set only one could not be called on a row already marked finished.
    That constraint found this signature — the first version took no status and could
    not be used at all.
    """
    if status not in FAILED_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(FAILED_STATUSES)}, got {status!r}. A call that "
            f"succeeded has a generation row; use record_generation_cost."
        )
    row = record_call(
        session,
        ref_table="job",
        ref_id=job.id,
        provider=job.provider,
        units=units,
        unit_price=unit_price,
        price_verified_on=price_verified_on,
    )
    job.status = status
    job.cost_usd = row.total_usd
    job.completed_at = job.completed_at or dt.datetime.now(dt.UTC)
    session.flush()
    return row


# ------------------------------------------------------------------ queries --
def spend_total(session: Session) -> Decimal:
    total = session.execute(select(func.coalesce(func.sum(CostLedger.total_usd), 0))).scalar_one()
    return Decimal(total)


def spend_since(session: Session, since: dt.datetime) -> Decimal:
    total = session.execute(
        select(func.coalesce(func.sum(CostLedger.total_usd), 0)).where(
            CostLedger.created_at >= since
        )
    ).scalar_one()
    return Decimal(total)


def month_start(now: dt.datetime | None = None) -> dt.datetime:
    moment = now or dt.datetime.now(dt.UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spend_this_month(session: Session, now: dt.datetime | None = None) -> Decimal:
    """Calendar month to date, which is what a monthly ceiling means.

    Deliberately a calendar month and not a rolling 30 days: a ceiling nobody can
    compute in their head is a ceiling nobody trusts.
    """
    return spend_since(session, month_start(now))


def spend_for_piece(session: Session, content_piece_id: uuid.UUID) -> Decimal:
    """Everything spent on one content piece, across every stage and failed call.

    Joins through the tables that reference a piece, so a take that failed after
    billing counts — otherwise per-piece cost understates exactly the spend a
    per-piece ceiling exists to catch.
    """
    from app.models import Shot, VoiceLine

    generation_ids = (
        select(Generation.id)
        .join(Shot, Shot.id == Generation.shot_id)
        .where(Shot.content_piece_id == content_piece_id)
    )
    voice_ids = (
        select(VoiceLine.id)
        .join(Shot, Shot.id == VoiceLine.shot_id)
        .where(Shot.content_piece_id == content_piece_id)
    )
    job_ids = select(Job.id).where(Job.generation_id.in_(generation_ids))

    total = session.execute(
        select(func.coalesce(func.sum(CostLedger.total_usd), 0)).where(
            ((CostLedger.ref_table == "generation") & CostLedger.ref_id.in_(generation_ids))
            | ((CostLedger.ref_table == "voice_line") & CostLedger.ref_id.in_(voice_ids))
            | ((CostLedger.ref_table == "job") & CostLedger.ref_id.in_(job_ids))
        )
    ).scalar_one()
    return Decimal(total)
