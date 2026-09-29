"""Database fixtures for the model tests.

The schema is created by running the migration, not by `Base.metadata.create_all`.
Those two can differ — that is exactly the drift `alembic check` exists to catch —
and a test suite that builds its schema from the models cannot see a broken
migration. Task 0.3 asks for the migration to run up and down, so the migration
is what the tests run against.

Without `DATABASE_URL` the whole module skips. The constraints under test are
Postgres features — a composite foreign key onto a unique pair, and `pgvector` —
so there is no in-memory substitute that would prove anything.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("DATABASE_URL", "").strip()

requires_db = pytest.mark.skipif(
    not DB_URL,
    reason="DATABASE_URL is not set; these tests need a real Postgres with pgvector",
)


def _alembic(*args: str, url: str) -> subprocess.CompletedProcess[str]:
    """Run alembic in a subprocess, the way a deploy does.

    In-process would share this session's SQLAlchemy state and could pass while
    the command a human types fails.
    """
    return subprocess.run(
        # sys.executable, not "python": the venv's interpreter is the one with
        # alembic installed, and a bare name resolves to whatever is first on PATH.
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env={**os.environ, "DATABASE_URL": url, "PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    """An engine against a database migrated to head."""
    result = _alembic("upgrade", "head", url=DB_URL)
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"
    engine = create_engine(DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def conn(migrated_engine: Engine) -> Iterator[Connection]:
    """A connection in a transaction that is always rolled back.

    Every test therefore sees the same empty schema, and nothing a test writes
    survives it.
    """
    connection = migrated_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def session(conn: Connection) -> Iterator[Session]:
    with Session(bind=conn, expire_on_commit=False) as db:
        yield db


@pytest.fixture
def persona_id(conn: Connection) -> str:
    row = conn.execute(
        text("INSERT INTO persona (name, status) VALUES ('Test Persona', 'draft') RETURNING id")
    ).one()
    return str(row[0])


@pytest.fixture
def disclosed_render(conn: Connection, persona_id: str) -> str:
    """A render that has been through the overlay pass."""
    piece: str = str(
        conn.execute(
            text(
                "INSERT INTO content_piece (persona_id, brief, format, status) "
                "VALUES (:p, 'brief', 'talking_head_course', 'assembled') RETURNING id"
            ),
            {"p": persona_id},
        ).scalar_one()
    )
    return str(
        conn.execute(
            text(
                "INSERT INTO render (content_piece_id, aspect, disclosure_applied) "
                "VALUES (:c, '9:16', true) RETURNING id"
            ),
            {"c": piece},
        ).scalar_one()
    )


@pytest.fixture
def undisclosed_render(conn: Connection, persona_id: str) -> str:
    """A render that has NOT had the overlay applied. Must never be publishable."""
    piece: str = str(
        conn.execute(
            text(
                "INSERT INTO content_piece (persona_id, brief, format, status) "
                "VALUES (:p, 'brief', 'talking_head_course', 'assembled') RETURNING id"
            ),
            {"p": persona_id},
        ).scalar_one()
    )
    return str(
        conn.execute(
            text(
                "INSERT INTO render (content_piece_id, aspect, disclosure_applied) "
                "VALUES (:c, '9:16', false) RETURNING id"
            ),
            {"c": piece},
        ).scalar_one()
    )
