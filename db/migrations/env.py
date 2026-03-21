"""Alembic environment — async SQLAlchemy support.

Supports two modes:
1. CLI usage: ``alembic upgrade head`` — creates its own async engine.
2. Programmatic usage: ``Database.run_migrations()`` — receives a sync
   connection via ``config.attributes["connection"]``, avoiding the need
   for ``asyncio.run()`` (which would fail inside a running event loop).
"""

import asyncio
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Ignore false-positive REAL vs Float on SQLite (they are identical)."""
    if isinstance(inspected_type, sa.REAL) and isinstance(metadata_type, sa.Float):
        return False
    return None  # let Alembic decide


def do_run_migrations(connection):
    """Configure Alembic context and run migrations on a connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # Required for SQLite ALTER TABLE support
        compare_type=_compare_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Two paths:
    - **Programmatic** (from ``Database.run_migrations``): a sync connection
      is passed via ``config.attributes["connection"]``.  We use it directly
      — no ``asyncio.run()`` needed, so this works inside a running loop.
    - **CLI** (``alembic upgrade head``): we create our own async engine
      and call ``asyncio.run()``.
    """
    connection = config.attributes.get("connection")
    if connection is not None:
        # Programmatic path — already inside conn.run_sync(), just use it
        do_run_migrations(connection)
        return

    # CLI path — spin up our own async engine
    async def _run_async():
        connectable = async_engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        async with connectable.connect() as conn:
            await conn.run_sync(do_run_migrations)
        await connectable.dispose()

    asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
