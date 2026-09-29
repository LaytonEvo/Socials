"""The one convention for a decision nobody has made yet.

Any config string beginning `PENDING_` is an unmade decision. It loads, it
survives validation, and it raises `DecisionPending` the moment code asks for its
value.

There were three conventions before this — `PERSONA_NAME`, `PENDING_TASK_2_5`,
and `DECIDE` written in a comment — and a loader can detect none of them
reliably. A placeholder a loader cannot recognise is indistinguishable from a
value, which is how a literal `PENDING_TASK_2_5` ends up in a generated prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, TypeVar

from pydantic import BeforeValidator

from .errors import DecisionPending

PENDING_PREFIX = "PENDING_"


@dataclass(frozen=True)
class Pending:
    """A decision reserved for a human (BUILD_PLAN Section 1).

    Deliberately not falsy and deliberately not a string. Truthiness would let
    `if cfg.name:` silently skip it, and a str subclass would let it be
    concatenated into a prompt without anything noticing.
    """

    token: str

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Pending({self.token})"


def _coerce(value: object) -> object:
    if isinstance(value, str) and value.startswith(PENDING_PREFIX):
        return Pending(value)
    return value


T = TypeVar("T")

#: A field whose value may be an unmade decision. `Pendable[Decimal]` reads as
#: "a Decimal once somebody decides".
Pendable = Annotated[T | Pending, BeforeValidator(_coerce)]


def require(value: Pending | T, where: str, *, because: str = "") -> T:
    """Return a decided value, or explain which decision is blocking.

    Call this at the point of use. The message names the config path and the
    decision, because "PENDING_D8 is not a float" sends someone to read the
    loader, and "budget.monthly_usd is waiting on D8" sends them to the person
    who can answer it.
    """
    if isinstance(value, Pending):
        decision = value.token.removeprefix(PENDING_PREFIX)
        tail = f" {because}" if because else ""
        raise DecisionPending(
            f"{where} is waiting on {decision}, a human decision reserved by "
            f"BUILD_PLAN Section 1. Claude Code must not invent one.{tail}"
        )
    return value


def is_pending(value: object) -> bool:
    return isinstance(value, Pending)
