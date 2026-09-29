"""Engine and session factory.

The URL comes from the environment and nowhere else (CLAUDE.md), with no default:
a fallback to a local database is how a test suite silently passes against the
wrong data, and how a migration gets applied to a developer's laptop while
everyone believes it ran on staging.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL_VAR = "DATABASE_URL"


class DatabaseNotConfigured(RuntimeError):
    """`DATABASE_URL` is unset. Deliberately fatal rather than defaulted."""


def database_url() -> str:
    url = os.environ.get(DATABASE_URL_VAR, "").strip()
    if not url:
        raise DatabaseNotConfigured(
            f"{DATABASE_URL_VAR} is not set. It has no default on purpose: a fallback to a "
            f"local database is how a suite passes against the wrong data and how a "
            f"migration lands somewhere nobody intended. See .env.example."
        )
    return url


def make_engine(url: str | None = None, **kwargs: object) -> Engine:
    return create_engine(url or database_url(), future=True, **kwargs)  # type: ignore[arg-type]


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """A transaction that commits on success and rolls back on any exception.

    CLAUDE.md requires a paid call's `cost_ledger` row to be written in the same
    transaction as the call it pays for, so the unit of work has to be explicit
    rather than per-statement autocommit.
    """
    session = make_session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
