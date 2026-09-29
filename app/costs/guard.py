"""The budget guard. Every paid call goes through it.

Three things it does, and the distinction matters because only the third was
deferred:

1. **Refuses an unpriced or stale-priced call.** A price with no `verified_on`, or
   one older than `price_max_age_days`, cannot be known to be current, and a guard
   reserving against a stale price is a guard that understates.
2. **Refuses a run with no explicit budget** (amendment A7). This is what actually
   bounds spend today, and it is not affected by observe mode.
3. **Refuses a call that would pass a monthly or per-piece ceiling.** Deferred by the
   owner on 2026-09-29 — run it first, set a ceiling from real numbers. In observe
   mode this reports instead of refusing.

Observe mode is not "no guard". Points 1 and 2 still refuse, every call is still
priced, and every call still writes a ledger row. What is switched off is one of the
three refusals, and the code says so rather than leaving a null ceiling to mean
whatever the reader assumes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import BudgetConfig, ProvidersConfig, ProviderSlot

from .errors import BudgetExceeded, BudgetNotSet
from .ledger import spend_for_piece, spend_this_month


@dataclass(frozen=True)
class Reservation:
    """What the guard decided, and why.

    Returned rather than just "allowed", because in observe mode a call that WOULD
    have been refused still needs to be visible — otherwise observing produces no
    observation.
    """

    estimated_usd: Decimal
    month_to_date: Decimal
    piece_to_date: Decimal | None
    #: Set when a ceiling would have been passed but the guard is observing. This is
    #: the number to put in front of a human.
    would_have_refused: str | None = None
    #: Set when spend has passed `warn_at_fraction` of a ceiling.
    warning: str | None = None

    @property
    def observed_breach(self) -> bool:
        return self.would_have_refused is not None


class BudgetGuard:
    """Priced, bounded and recorded. Built from config, never from literals."""

    def __init__(self, budget: BudgetConfig, providers: ProvidersConfig) -> None:
        self._budget = budget.budget
        self._providers = providers

    # -------------------------------------------------------------- pricing --
    def price(
        self, group: str, slot: str, *, today: dt.date | None = None
    ) -> tuple[ProviderSlot, Decimal, str]:
        """The slot, its unit price and the unit — refusing if it cannot be trusted.

        Delegates the refusal to `ProviderSlot.require_usable`, so there is one
        implementation of "may this be billed against" rather than a second copy
        here that drifts.
        """
        chosen = self._providers.require_usable(group, slot, today)
        prices = chosen.prices()
        if len(prices) != 1:
            raise ValueError(
                f"providers.{group}.{slot} declares {sorted(prices)}; the guard cannot "
                f"tell which unit bills. Split the slot or price it in one unit."
            )
        unit, amount = next(iter(prices.items()))
        return chosen, amount, unit

    def estimate(self, group: str, slot: str, units: Decimal) -> Decimal:
        _, unit_price, _ = self.price(group, slot)
        return (units * unit_price).quantize(Decimal("0.000001"))

    # ------------------------------------------------------- per-run budget --
    def require_run_budget(self, run_budget_usd: Decimal | None) -> Decimal:
        """Amendment A7, and NOT part of what the owner deferred.

        With no monthly ceiling set, this is the only thing bounding spend. The spike
        already worked this way: every battery ran against a budget set deliberately.
        """
        if not self._budget.require_explicit_budget_per_run:
            return run_budget_usd if run_budget_usd is not None else Decimal("0")
        if run_budget_usd is None:
            raise BudgetNotSet(
                "this run has no budget. A paid provider call requires an explicit "
                "budget argument (BUILD_ORDER amendment A7) — and with no monthly "
                "ceiling set it is the only thing bounding spend at all."
            )
        if run_budget_usd <= 0:
            raise BudgetNotSet(f"a run budget must be positive, got {run_budget_usd}")
        return run_budget_usd

    # ------------------------------------------------------------- ceilings --
    def check(
        self,
        session: Session,
        *,
        estimated_usd: Decimal,
        content_piece_id: uuid.UUID | None = None,
        now: dt.datetime | None = None,
    ) -> Reservation:
        """Decide whether this call may be made. Called BEFORE the provider is."""
        month = spend_this_month(session, now)
        piece = spend_for_piece(session, content_piece_id) if content_piece_id is not None else None

        breach: str | None = None
        warning: str | None = None

        monthly = self._budget.monthly_usd
        if monthly is not None:
            projected = month + estimated_usd
            if projected > monthly:
                breach = (
                    f"this call would take month-to-date spend to ${projected} against a "
                    f"${monthly} monthly ceiling (spent ${month}, this call ${estimated_usd})"
                )
            elif projected > monthly * Decimal(str(self._budget.warn_at_fraction)):
                warning = (
                    f"month-to-date spend would reach ${projected}, past "
                    f"{self._budget.warn_at_fraction:.0%} of the ${monthly} ceiling"
                )

        per_piece = self._budget.per_piece_usd
        if breach is None and per_piece is not None and piece is not None:
            projected_piece = piece + estimated_usd
            if projected_piece > per_piece:
                breach = (
                    f"this call would take spend on this piece to ${projected_piece} "
                    f"against a ${per_piece} per-piece ceiling"
                )

        if breach is not None and not self._budget.observing:
            ceiling = monthly if monthly is not None else per_piece
            assert ceiling is not None
            raise BudgetExceeded(
                f"{breach}. Refused before the call was made.",
                spent=month,
                ceiling=ceiling,
            )

        return Reservation(
            estimated_usd=estimated_usd,
            month_to_date=month,
            piece_to_date=piece,
            would_have_refused=breach if self._budget.observing else None,
            warning=warning,
        )
