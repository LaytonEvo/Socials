"""Enqueuing, from the web process or a script.

`enqueue` insists on a job id. arq generates a random one otherwise, and a random
id means an enqueue that happens twice — a double-clicked button, a retried HTTP
request, a worker restart mid-dispatch — runs the work twice. For a job that
spends money that is a second charge, so the deduplicating id is not optional here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis
from arq.jobs import Job

from .settings import redis_settings


@asynccontextmanager
async def queue(url: str | None = None) -> AsyncIterator[ArqRedis]:
    """A connection to the queue, closed on exit."""
    pool = await create_pool(redis_settings(url))
    try:
        yield pool
    finally:
        await pool.aclose()


async def enqueue(
    pool: ArqRedis, function: str, *args: Any, job_id: str, **kwargs: Any
) -> Job | None:
    """Enqueue one job under a caller-chosen id.

    Returns None when a job with that id is already queued or running, which is
    arq's way of saying "already accepted" and is a success, not a failure. The
    caller decides whether that matters; for a paid call it usually means stop.
    """
    return await pool.enqueue_job(function, *args, _job_id=job_id, **kwargs)
