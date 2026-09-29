"""Job definitions.

The skeleton, per task 0.5. Two jobs exist so far and neither generates anything:
`ping` proves a job round-trips, and `health` proves a worker can reach the things
it will need. The generation jobs arrive with task 3.4.

Every function here takes arq's `ctx` first and returns something JSON-serialisable,
because a return value travels through Redis.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from arq import Retry
from sqlalchemy import text


async def ping(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """The round-trip test job.

    Returns the worker's own view of the call, so a test can tell the work really
    happened in the worker rather than in the enqueuing process.
    """
    return {
        "message": message,
        "job_id": ctx.get("job_id"),
        "job_try": ctx.get("job_try"),
        "handled_at": dt.datetime.now(dt.UTC).isoformat(),
    }


async def health(ctx: dict[str, Any]) -> dict[str, Any]:
    """Confirm the worker can reach Postgres and object storage.

    Worth having as a job rather than only as a startup check: a worker can start
    healthy and lose the database later, and the queue is where that becomes
    visible.
    """
    checks: dict[str, Any] = {"database": False, "storage": False}

    engine = ctx.get("engine")
    if engine is not None:
        with engine.connect() as conn:
            checks["database"] = conn.execute(text("SELECT 1")).scalar_one() == 1

    try:
        from app.storage import from_env

        backend = from_env()
        checks["storage"] = backend.name
    except Exception as exc:  # a health check reports what is wrong; it does not raise
        checks["storage"] = f"unavailable: {type(exc).__name__}"

    return checks


async def always_fails(ctx: dict[str, Any]) -> str:
    """Raises an ordinary exception, every time.

    Pins arq's actual behaviour, which is easy to get backwards: an ordinary
    exception FAILS the job and is not retried, whatever `max_tries` says. Only
    `arq.Retry` and cancellation are retried. That distinction decides whether a
    paid call can be charged twice, so it is worth a test rather than a comment.
    """
    raise RuntimeError("this job always fails")


async def retry_once(ctx: dict[str, Any]) -> str:
    """Asks to be retried once, the way an idempotent job opts in.

    Kept in the shipped function list rather than defined in a test, because what
    is under test is the worker's own configuration — a job registered only in a
    test would run under a different worker than the one that ships.
    """
    if ctx.get("job_try", 1) < 2:
        raise Retry(defer=0)
    return "succeeded on retry"


#: The registry arq reads. A job missing from here is silently unrunnable: the
#: enqueue succeeds and the worker rejects it, so the failure shows up as a job
#: that never completes.
FUNCTIONS = [ping, health, always_fails, retry_once]
