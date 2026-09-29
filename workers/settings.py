"""Worker configuration — Redis connection, timeouts, and the retry policy.

The retry policy is the part that matters, and arq's actual semantics are narrower
than they look. Reading `arq.worker.Worker.run_job`: a job that raises an ordinary
exception **fails and is not retried**. `max_tries` bounds two other cases — a job
that raises `arq.Retry` deliberately, and a job whose task is cancelled, which is
what happens when the worker is killed mid-job or the job exceeds `job_timeout`.

That second case is the expensive one, and it is why the default here is **one
attempt**. A deploy sends SIGTERM to the worker halfway through a video take; arq's
default `max_tries` of 5 would re-queue the job and the provider would be called
again — while the first call, already generating, is already billed. Nothing about
the second attempt knows that. So a job is retried only when it asks to be.

Amendment A2 is the other half. A provider call gets a `job` row from submit to
outcome whether or not it produced anything, so a retry can see that a previous
attempt was billed instead of rediscovering it from the invoice.
"""

from __future__ import annotations

import os
from typing import Any

from arq.connections import RedisSettings

from .jobs import FUNCTIONS

REDIS_URL_VAR = "REDIS_URL"

#: One attempt. arq's default of 5 applies to cancellation as well as to an
#: explicit `Retry`, so a worker killed mid-generation would re-run a call the
#: provider has already billed. A job that is genuinely idempotent, or cheap,
#: overrides this with its own `max_tries`.
DEFAULT_MAX_TRIES = 1

#: Generation is slow. A video take runs several minutes and a LoRA training job
#: far longer, so arq's 300 s default would cancel work that was proceeding
#: normally — after the provider had been paid, and (with a higher max_tries)
#: straight into paying again.
DEFAULT_JOB_TIMEOUT_S = 30 * 60

#: How long a finished job's result stays in Redis. Long enough for the web
#: process to collect it, short enough that Redis is not a database. The durable
#: record is the `job` table; Redis is the queue.
RESULT_TTL_S = 60 * 60


class RedisNotConfigured(RuntimeError):
    """`REDIS_URL` is unset. Deliberately fatal rather than defaulted to localhost."""


def redis_url() -> str:
    url = os.environ.get(REDIS_URL_VAR, "").strip()
    if not url:
        raise RedisNotConfigured(
            f"{REDIS_URL_VAR} is not set. It has no default, for the same reason "
            f"DATABASE_URL has none: a fallback to localhost is how a worker quietly "
            f"consumes a different queue from the one the web process fills, and "
            f"nothing reports it. See .env.example."
        )
    return url


def redis_settings(url: str | None = None) -> RedisSettings:
    return RedisSettings.from_dsn(url or redis_url())


async def on_startup(ctx: dict[str, Any]) -> None:
    """Fail loudly at boot if the worker cannot reach what it needs.

    A worker that starts, accepts a job and then cannot reach Postgres looks
    identical to a slow queue: jobs go in, nothing comes out, and the logs are on a
    container nobody is watching. Checking at startup turns that into a crash loop,
    which is visible.
    """
    from app.models import make_engine

    engine = make_engine()
    with engine.connect():
        pass
    ctx["engine"] = engine


async def on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.pop("engine", None)
    if engine is not None:
        engine.dispose()


class _LazyRedis(type):
    """Gives `WorkerSettings.redis_settings` to arq as an attribute, resolved late.

    arq's CLI reads `WorkerSettings.redis_settings` as a value, not as a method, so
    a `@staticmethod` returning RedisSettings boots and then dies on
    `settings.host`. Making it a plain class attribute instead would build the
    settings at import time, which means importing this module without REDIS_URL
    set — as every test that does not need a queue does — would fail.

    A property on the metaclass gives both: attribute access for arq, evaluated
    only when something actually asks.
    """

    @property
    def redis_settings(cls) -> RedisSettings:
        return redis_settings()


class WorkerSettings(metaclass=_LazyRedis):
    """arq's entry point: `arq workers.settings.WorkerSettings`."""

    functions = FUNCTIONS

    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)

    max_tries = DEFAULT_MAX_TRIES
    job_timeout = DEFAULT_JOB_TIMEOUT_S
    keep_result = RESULT_TTL_S

    #: Generation calls are I/O-bound waits on a provider, not CPU work, so a
    #: worker can hold several at once. Kept modest because each concurrent take
    #: is money in flight, and the budget guard (task 0.7) is the thing that
    #: should decide how much — not a concurrency number nobody revisits.
    max_jobs = 4
