"""Task 0.3 — "migration runs up and down".

Down is the half that usually goes untested, and the half you need at the worst
possible moment. These run against a database of their own, created and dropped
here, because a downgrade drops every table and would take the other tests'
schema with it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.models import Base

from .conftest import DB_URL, _alembic, requires_db

pytestmark = requires_db

ROUNDTRIP_DB = "persona_studio_roundtrip"


@pytest.fixture
def roundtrip_url() -> Iterator[str]:
    """A throwaway database, so a downgrade here cannot affect anything else."""
    admin = create_engine(DB_URL, isolation_level="AUTOCOMMIT", future=True)
    # render_as_string(hide_password=False), not str(): str() on a SQLAlchemy URL
    # replaces the password with ***, which then fails authentication with a
    # message that looks like a credentials problem rather than a masking one.
    url = make_url(DB_URL).set(database=ROUNDTRIP_DB).render_as_string(hide_password=False)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{ROUNDTRIP_DB}"'))
            conn.execute(text(f'CREATE DATABASE "{ROUNDTRIP_DB}"'))
    except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - permissions vary
        pytest.skip(f"cannot create a scratch database: {exc}")
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": ROUNDTRIP_DB},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{ROUNDTRIP_DB}"'))
        admin.dispose()


def _table_names(url: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            return set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()


def test_the_migration_runs_up_from_an_empty_database(roundtrip_url: str) -> None:
    """Including creating the pgvector extension, which autogenerate cannot know about."""
    assert _table_names(roundtrip_url) == set()

    result = _alembic("upgrade", "head", url=roundtrip_url)
    assert result.returncode == 0, result.stderr

    tables = _table_names(roundtrip_url)
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert tables == expected, f"missing {expected - tables}, unexpected {tables - expected}"


def test_the_migration_runs_back_down_to_nothing(roundtrip_url: str) -> None:
    """A downgrade that leaves tables behind is a downgrade that cannot be relied on."""
    assert _alembic("upgrade", "head", url=roundtrip_url).returncode == 0

    result = _alembic("downgrade", "base", url=roundtrip_url)
    assert result.returncode == 0, result.stderr

    left = _table_names(roundtrip_url) - {"alembic_version"}
    assert left == set(), f"downgrade left tables behind: {sorted(left)}"


def test_the_migration_is_idempotent_across_a_full_cycle(roundtrip_url: str) -> None:
    """Up, down, up again. The second up is where a missing CREATE EXTENSION shows."""
    for _ in range(2):
        assert _alembic("upgrade", "head", url=roundtrip_url).returncode == 0
        assert _alembic("downgrade", "base", url=roundtrip_url).returncode == 0
    assert _alembic("upgrade", "head", url=roundtrip_url).returncode == 0
    assert "reference_asset" in _table_names(roundtrip_url)


def test_the_models_and_the_migration_do_not_disagree(roundtrip_url: str) -> None:
    """`alembic check` against a freshly migrated database.

    This is the test that catches a model changed without a migration — the drift
    that is invisible until a deploy, and the reason `compare_type` and
    `compare_server_default` are enabled in env.py.
    """
    assert _alembic("upgrade", "head", url=roundtrip_url).returncode == 0

    result = _alembic("check", url=roundtrip_url)
    assert result.returncode == 0, (
        "the models and the migrations have diverged. Generate a migration:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_no_not_null_column_relies_on_a_python_side_default() -> None:
    """A defect this suite found rather than assumed.

    SQLAlchemy's `default=` is applied by the ORM, in Python. A NOT NULL column
    carrying only that is a column which rejects every insert made any other way:
    raw SQL, COPY, a hand fix in psql, a future service in another language. The
    first version of this schema had twelve of them, and the constraint tests
    failed on NOT NULL violations rather than on the constraints they were written
    to check.
    """
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if not column.nullable and column.default is not None and column.server_default is None
    ]
    assert not offenders, (
        f"these NOT NULL columns default only in Python, so raw SQL cannot insert them: {offenders}"
    )


def test_every_check_constraint_is_named() -> None:
    """An unnamed constraint cannot be asserted on, or dropped in a later migration."""
    unnamed = [
        f"{table.name}.{type(constraint).__name__}"
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint) and not constraint.name
    ]
    assert not unnamed


def test_a_connection_is_never_defaulted(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DATABASE_URL` has no fallback, on purpose."""
    from app.models import DatabaseNotConfigured, database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseNotConfigured, match="no default on purpose"):
        database_url()
