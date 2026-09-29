"""Cost ledger and budget guard.

Every paid API call goes through the guard and writes a `cost_ledger` row in the same
transaction (CLAUDE.md). The guard refuses a job that would exceed a ceiling *before*
the call is made.

Two rules the spike learned the hard way:

- **A price without a `verified_on` date is refused**, as is one older than
  `price_max_age_days`. A stale price is a silent overspend.
- **Where a provider publishes more than one rate, the guard takes the higher.** A
  guard that understates lets a run sail past the cap while reporting it is inside
  it; over-reserving spends less than budgeted, which is the safe direction to be
  wrong in.

Amendment A7, now enforced: no live provider call outside an explicitly budgeted run.
With D8's ceilings deliberately unset until there is real spend to set them from,
this is the only thing bounding spend — so it refuses rather than warns.
"""

from __future__ import annotations

from .errors import BudgetExceeded, BudgetNotSet, CostError, LedgerIncomplete
from .guard import BudgetGuard, Reservation
from .ledger import (
    FAILED_STATUSES,
    REF_TABLES,
    month_start,
    record_call,
    record_failed_call,
    record_generation_cost,
    spend_for_piece,
    spend_since,
    spend_this_month,
    spend_total,
)

__all__ = [
    "FAILED_STATUSES",
    "REF_TABLES",
    "BudgetExceeded",
    "BudgetGuard",
    "BudgetNotSet",
    "CostError",
    "LedgerIncomplete",
    "Reservation",
    "month_start",
    "record_call",
    "record_failed_call",
    "record_generation_cost",
    "spend_for_piece",
    "spend_since",
    "spend_this_month",
    "spend_total",
]
