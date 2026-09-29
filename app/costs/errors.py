"""Cost guard errors."""

from __future__ import annotations

from decimal import Decimal


class CostError(Exception):
    """Base for every spend failure."""


class BudgetExceeded(CostError):
    """The call would take spend past a ceiling. Raised BEFORE the call is made."""

    def __init__(self, message: str, *, spent: Decimal, ceiling: Decimal) -> None:
        super().__init__(message)
        self.spent = spent
        self.ceiling = ceiling


class BudgetNotSet(CostError):
    """No per-run budget was supplied.

    Amendment A7: no live provider call outside an explicitly budgeted run. This is
    what bounds spend while the monthly ceiling is unset, so it is a hard refusal
    rather than a warning.
    """


class LedgerIncomplete(CostError):
    """A cost was recorded without the row that makes it auditable, or vice versa.

    CLAUDE.md requires the ledger row and the cost column to be written in the same
    transaction. This is raised when something tried to do one without the other.
    """
