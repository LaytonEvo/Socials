"""Cost ledger and budget guard.

Every paid call in the spike goes through :meth:`CostLedger.paid_call`. There
is deliberately no other path: a second way to spend money is a second way to
spend money by accident.

The guard refuses BEFORE the call, using the provider's own cost estimate. The
actual cost is recorded after. When the two differ, the difference is logged --
that gap is one of the things Spike 0 exists to measure, because the Phase 0
cost guard (BUILD_PLAN task 0.7) will be designed against it.

Failed calls are recorded too. A provider call that times out has still been
paid for, and BUILD_ORDER amendment A2 exists because the production schema
has nowhere to put that.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, TypeVar

from .config import ProviderConfig
from .errors import BudgetExceeded, BudgetNotSet
from .runlog import RunLog

T = TypeVar("T")


@dataclass
class CallOutcome:
    """What a paid call actually cost, reported by the caller."""

    units: float
    ok: bool = True
    error: str | None = None
    # None means "charge the estimate"; providers that report real usage
    # should pass the true figure.
    actual_usd: Decimal | None = None


@dataclass
class CostLedger:
    """Budget guard for one run. ``budget_usd`` is mandatory."""

    budget_usd: Decimal
    log: RunLog
    price_max_age_days: int = 90
    today: dt.date = field(default_factory=dt.date.today)
    _spent: Decimal = field(default=Decimal("0"), init=False)
    _entries: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.budget_usd is None:
            raise BudgetNotSet(
                "A run that can spend money needs an explicit budget. "
                "BUILD_ORDER amendment A7: no live provider call outside an "
                "explicitly budgeted run."
            )
        if self.budget_usd < 0:
            raise BudgetNotSet(f"Budget must not be negative, got {self.budget_usd}")
        self.log.event("budget_set", budget_usd=str(self.budget_usd))

    @property
    def spent(self) -> Decimal:
        return self._spent

    @property
    def remaining(self) -> Decimal:
        return self.budget_usd - self._spent

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    @property
    def has_fake_spend(self) -> bool:
        """True if any entry came from a stub provider.

        Gate A reporting keys off this: fake evidence must never reach a human
        go/no-go decision unnoticed.
        """
        return any(e["is_fake"] for e in self._entries)

    def estimate(self, provider: ProviderConfig, units: float) -> Decimal:
        provider.require_usable(self.today, self.price_max_age_days)
        assert provider.price is not None  # require_usable guarantees this
        return (Decimal(str(provider.price)) * Decimal(str(units))).quantize(Decimal("0.000001"))

    def check_affordable(self, provider: ProviderConfig, units: float) -> Decimal:
        """Raise unless an estimated call fits in what is left."""
        est = self.estimate(provider, units)
        if self._spent + est > self.budget_usd:
            raise BudgetExceeded(
                f"Refusing {provider.kind}/{provider.slot} call: estimated ${est} "
                f"would take the run to ${self._spent + est} against a budget of "
                f"${self.budget_usd} (${self.remaining} left). No call was made."
            )
        return est

    @contextmanager
    def paid_call(
        self,
        provider: ProviderConfig,
        units: float,
        ref: str,
        **context: Any,
    ) -> Iterator[CallOutcome]:
        """The single choke point for spending money.

        Checks affordability, yields a :class:`CallOutcome` for the caller to
        fill in, then records the entry -- including when the call raised.
        """
        estimated = self.check_affordable(provider, units)
        outcome = CallOutcome(units=units)
        self.log.event(
            "call_reserved",
            ref=ref,
            provider_kind=provider.kind,
            provider_slot=provider.slot,
            model=provider.model,
            units=units,
            estimated_usd=str(estimated),
            **context,
        )
        try:
            yield outcome
        except Exception as exc:
            outcome.ok = False
            outcome.error = f"{type(exc).__name__}: {exc}"
            # A call the provider refused before starting work cost nothing, and
            # charging for it would exhaust a budget on calls that never ran --
            # then report a budget error instead of the auth failure that caused
            # it. Anything else is assumed billed: over-recording is the safe
            # direction, under-recording lets a run sail past its cap.
            if not getattr(exc, "billable", True):
                outcome.units = 0.0
                outcome.actual_usd = Decimal("0")
            self._record(provider, outcome, estimated, ref, context)
            raise
        self._record(provider, outcome, estimated, ref, context)

    def _record(
        self,
        provider: ProviderConfig,
        outcome: CallOutcome,
        estimated: Decimal,
        ref: str,
        context: dict[str, Any],
    ) -> None:
        actual = outcome.actual_usd if outcome.actual_usd is not None else estimated
        if outcome.actual_usd is None and outcome.units != 0:
            actual = self.estimate(provider, outcome.units)
        self._spent += actual
        entry = {
            "ref": ref,
            "provider_kind": provider.kind,
            "provider_slot": provider.slot,
            "model": provider.model,
            "units": outcome.units,
            "unit_price": str(provider.price),
            "price_verified_on": provider.verified_on.isoformat() if provider.verified_on else None,
            "estimated_usd": str(estimated),
            "total_usd": str(actual),
            "estimate_error_usd": str(actual - estimated),
            "ok": outcome.ok,
            "error": outcome.error,
            "is_fake": provider.is_fake,
            "running_total_usd": str(self._spent),
            **context,
        }
        self._entries.append(entry)
        self.log.event("cost", **entry)

    def spend_guard(
        self,
        provider: ProviderConfig,
        units: float,
        ref: str,
        fn: Callable[[], T],
        **context: Any,
    ) -> T:
        """Convenience wrapper: run ``fn`` as a single guarded paid call."""
        with self.paid_call(provider, units, ref, **context) as outcome:
            result = fn()
            outcome.ok = True
        return result

    def summary(self) -> dict[str, Any]:
        by_slot: dict[str, dict[str, Any]] = {}
        for e in self._entries:
            key = f"{e['provider_kind']}/{e['provider_slot']}"
            agg = by_slot.setdefault(
                key, {"calls": 0, "failed": 0, "units": 0.0, "total_usd": Decimal("0")}
            )
            agg["calls"] += 1
            agg["failed"] += 0 if e["ok"] else 1
            agg["units"] += float(e["units"])
            agg["total_usd"] += Decimal(e["total_usd"])
        return {
            "budget_usd": str(self.budget_usd),
            "spent_usd": str(self._spent),
            "remaining_usd": str(self.remaining),
            "calls": len(self._entries),
            "failed_calls": sum(1 for e in self._entries if not e["ok"]),
            "contains_fake_spend": self.has_fake_spend,
            "by_provider": {k: {**v, "total_usd": str(v["total_usd"])} for k, v in by_slot.items()},
        }
