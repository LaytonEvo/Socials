"""Task 0.5 — the job queue and worker skeleton.

The acceptance criterion is "a test job round-trips", and round-trip is taken
literally: a real Redis, a real arq worker, the job executed by the worker rather
than by the test, and the result read back out of the queue. An in-process fake
would prove the function returns a dict, which is not the thing that breaks.

Skipped without `REDIS_URL`, like the database tests are without `DATABASE_URL`,
and CI has the same guard that fails the build if they skip there.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from arq import Worker
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus

from workers.jobs import FUNCTIONS, ping
from workers.queue import enqueue, queue
from workers.settings import (
    DEFAULT_JOB_TIMEOUT_S,
    DEFAULT_MAX_TRIES,
    RESULT_TTL_S,
    RedisNotConfigured,
    WorkerSettings,
    redis_settings,
    redis_url,
)

REDIS_URL = os.environ.get("REDIS_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not REDIS_URL, reason="REDIS_URL is not set; the queue tests need a real Redis"
)


@pytest.fixture
async def pool() -> AsyncIterator[ArqRedis]:
    async with queue(REDIS_URL) as connection:
        await connection.flushdb()
        yield connection


async def _run_until_empty(pool: ArqRedis, *, max_tries: int = DEFAULT_MAX_TRIES) -> None:
    """Run a real worker in burst mode until the queue drains."""
    worker = Worker(
        functions=FUNCTIONS,
        redis_pool=pool,
        max_tries=max_tries,
        job_timeout=10,
        keep_result=RESULT_TTL_S,
        burst=True,
        poll_delay=0.01,
    )
    await worker.async_run()


# --------------------------------------------------------------- round-trip --
async def test_a_job_round_trips_through_redis_and_a_worker(pool: ArqRedis) -> None:
    """Enqueue, let a worker execute it, read the result back. The point of 0.5."""
    job = await enqueue(pool, "ping", "hello from the test", job_id="roundtrip-1")
    assert job is not None
    assert await job.status() == JobStatus.queued

    await _run_until_empty(pool)

    result = await job.result(timeout=5)
    assert result["message"] == "hello from the test"
    assert result["job_id"] == "roundtrip-1"
    assert await job.status() == JobStatus.complete


async def test_the_work_happens_in_the_worker_not_the_caller(pool: ArqRedis) -> None:
    """A queue that executed inline would pass every other test here.

    Before the worker runs, the job is queued and has no result. That ordering is
    what distinguishes a real queue from a function call.
    """
    job = await enqueue(pool, "ping", job_id="deferred-1")
    assert job is not None
    assert await job.status() == JobStatus.queued
    with pytest.raises(asyncio.TimeoutError):
        await job.result(timeout=0.2)

    await _run_until_empty(pool)
    assert (await job.result(timeout=5))["message"] == "pong"


async def test_a_result_can_be_collected_by_another_process(pool: ArqRedis) -> None:
    """The web process reads the result by id, after the worker has moved on."""
    job = await enqueue(pool, "ping", "kept", job_id="ttl-1")
    assert job is not None
    await _run_until_empty(pool)
    assert (await Job("ttl-1", pool).result(timeout=5))["message"] == "kept"


# ------------------------------------------------------------ deduplication --
async def test_the_same_job_id_is_only_accepted_once(pool: ArqRedis) -> None:
    """A double-clicked button must not buy two takes.

    arq returns None for a duplicate id, which is "already accepted" rather than a
    failure. The caller decides what that means; for a paid call it means stop.
    """
    first = await enqueue(pool, "ping", job_id="dedupe-1")
    second = await enqueue(pool, "ping", job_id="dedupe-1")
    assert first is not None
    assert second is None

    await _run_until_empty(pool)
    assert (await first.result(timeout=5))["job_try"] == 1


async def test_different_ids_are_separate_jobs(pool: ArqRedis) -> None:
    ids = [f"distinct-{n}" for n in range(3)]
    for job_id in ids:
        assert await enqueue(pool, "ping", job_id=job_id) is not None

    await _run_until_empty(pool)
    results = [await Job(job_id, pool).result(timeout=5) for job_id in ids]
    assert {r["job_id"] for r in results} == set(ids)


async def test_an_id_is_required_to_enqueue() -> None:
    """A random id means an enqueue that happens twice runs the work twice."""
    with pytest.raises(TypeError):
        await enqueue(None, "ping")  # type: ignore[arg-type,call-arg]


# ------------------------------------------------------------- retry policy --
async def test_an_ordinary_exception_is_never_retried(pool: ArqRedis) -> None:
    """Pins arq's real behaviour, which is easy to assume backwards.

    A job that raises an ordinary exception FAILS. `max_tries` does not bring it
    back, even set high — only `arq.Retry` and cancellation are retried. Reading
    `Worker.run_job` is what established this; the first version of this module
    documented the opposite.
    """
    job = await enqueue(pool, "always_fails", job_id="plainfail-1")
    assert job is not None

    await _run_until_empty(pool, max_tries=5)

    with pytest.raises(RuntimeError, match="always fails"):
        await job.result(timeout=5)
    info = await job.info()
    assert info is not None
    assert info.job_try == 1, "an ordinary exception was retried; the policy has changed"


async def test_a_job_that_asks_to_be_retried_is(pool: ArqRedis) -> None:
    """The opt-in path, for a job that is idempotent or cheap enough."""
    job = await enqueue(pool, "retry_once", job_id="retry-1")
    assert job is not None

    await _run_until_empty(pool, max_tries=3)

    assert await job.result(timeout=5) == "succeeded on retry"


async def test_the_default_refuses_even_a_requested_retry(pool: ArqRedis) -> None:
    """max_tries=1 is a hard stop, which is what makes it a safety property.

    A worker killed mid-generation is the case this protects: arq treats the
    cancellation as retryable, and a retry would call a provider that has already
    billed for the first attempt.
    """
    job = await enqueue(pool, "retry_once", job_id="retry-blocked-1")
    assert job is not None

    await _run_until_empty(pool)

    with pytest.raises(Exception, match="retries exceeded"):
        await job.result(timeout=5)


def test_the_shipped_default_is_one_attempt() -> None:
    assert DEFAULT_MAX_TRIES == 1
    assert WorkerSettings.max_tries == 1


def test_the_job_timeout_allows_for_a_slow_generation() -> None:
    """arq's 300 s default would kill a video take that was proceeding normally,
    and kill it after the provider had been paid."""
    assert DEFAULT_JOB_TIMEOUT_S >= 15 * 60
    assert WorkerSettings.job_timeout == DEFAULT_JOB_TIMEOUT_S


def test_every_job_is_registered_with_the_worker() -> None:
    """A job missing from FUNCTIONS enqueues fine and is then silently unrunnable."""
    assert ping in FUNCTIONS
    assert {f.__name__ for f in FUNCTIONS} == {
        "ping",
        "health",
        "always_fails",
        "retry_once",
    }


# --------------------------------------------------------------- the worker --
async def test_the_worker_reports_what_it_cannot_reach(pool: ArqRedis) -> None:
    """A worker that starts and then cannot reach Postgres looks like a slow queue.

    The health job makes that difference visible. Here it runs with no engine in
    context — exactly the broken case — and it reports rather than raising.
    """
    job = await enqueue(pool, "health", job_id="health-1")
    assert job is not None
    await _run_until_empty(pool)

    checks = await job.result(timeout=5)
    assert checks["database"] is False
    assert "storage" in checks


# ------------------------------------------------------------ configuration --
def test_redis_is_never_defaulted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fallback to localhost is how a worker consumes a different queue from the
    one the web process fills, with nothing reporting it."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(RedisNotConfigured, match="no default"):
        redis_url()


def test_a_dsn_becomes_redis_settings() -> None:
    settings = redis_settings("redis://127.0.0.1:6379/3")
    assert settings.host == "127.0.0.1"
    assert settings.port == 6379
    assert settings.database == 3


def test_arq_reads_redis_settings_as_an_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    """How arq's CLI actually reads it, which is not how it looks.

    A @staticmethod returning RedisSettings passes a test that calls it, boots the
    worker, and then dies on `settings.host` because arq never called it. That is
    exactly what happened here, and only running `arq workers.settings.WorkerSettings`
    showed it — so this test accesses the attribute the way arq does.
    """
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6380/1")
    settings = WorkerSettings.redis_settings
    assert isinstance(settings, RedisSettings)
    assert settings.host == "example.invalid"
    assert settings.port == 6380


def test_the_settings_module_imports_without_a_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolved late, so every test that does not need a queue can still import this.

    Building RedisSettings at class-definition time would be the obvious fix for the
    attribute problem above, and would make an unset REDIS_URL an import error.
    """
    monkeypatch.delenv("REDIS_URL", raising=False)
    # No importlib.reload here. The class was already imported at module load, so if
    # the settings were built at class-definition time this test could not run at
    # all — the import would have failed. Accessing the attribute now, with the
    # variable unset, is the whole proof.
    #
    # (A reload would also compare the wrong exception: it rebinds
    # RedisNotConfigured to a new class object, so `pytest.raises` on the imported
    # one never matches.)
    with pytest.raises(RedisNotConfigured, match="no default"):
        _ = WorkerSettings.redis_settings
