"""Alembic environment.

Two deliberate departures from the generated template:

- **The URL comes from the environment, not from alembic.ini.** A connection
  string in a committed file is a secret in the repository, and a default is how
  a migration lands on the wrong database.
- **`compare_type` and `compare_server_default` are on.** Without them
  autogenerate silently misses a column whose type or default changed, which is
  the class of drift nobody notices until a deploy.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from pgvector.sqlalchemy import Vector
from sqlalchemy import engine_from_config, pool

from app.models import Base, database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `%` doubled because `set_main_option` writes through configparser, where a bare `%` is
# interpolation syntax. A managed-Postgres URL routinely contains percent-encoding — `%40`
# for `@` in a password, `%2F` for `/` — and alembic then fails with "invalid interpolation
# syntax at position N" rather than anything about the password. Found 2026-10-01 when a
# unix-socket URL (`?host=%2Fvar%2Ftmp`) broke all four migration tests.
config.set_main_option("sqlalchemy.url", database_url().replace("%", "%%"))
target_metadata = Base.metadata


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Leave pgvector's own tables alone if the extension ever adds any."""
    return not (type_ == "table" and name is not None and name.startswith("vector_"))


def _render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render a pgvector column with the import it needs.

    Autogenerate renders `Vector` as `pgvector.sqlalchemy.vector.VECTOR(dim=N)`
    and does not add the import, so the generated migration raises NameError the
    first time it runs. Fixing the file by hand fixes one migration; this fixes
    every future one.
    """
    if type_ == "type" and isinstance(obj, Vector):
        imports = getattr(autogen_context, "imports", None)
        if imports is not None:
            imports.add("import pgvector.sqlalchemy")
        return f"pgvector.sqlalchemy.Vector(dim={obj.dim})"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
            render_item=_render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
