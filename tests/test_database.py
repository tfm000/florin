"""Tests for db.database — engine init, migrations, and table creation."""

import pytest

from db.database import Database
from db.models import Base


class TestDatabaseInit:
    @pytest.mark.asyncio
    async def test_init_creates_engine_and_session_factory(self):
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init()
        assert db._engine is not None
        assert db._session_factory is not None
        await db.close()

    @pytest.mark.asyncio
    async def test_init_does_not_create_tables(self):
        """init() should NOT create tables — that's Alembic's job."""
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init()

        from sqlalchemy import inspect

        async with db._engine.connect() as conn:
            table_names = await conn.run_sync(lambda c: inspect(c).get_table_names())

        assert len(table_names) == 0, f"init() should not create tables, but found: {table_names}"
        await db.close()

    @pytest.mark.asyncio
    async def test_create_tables_for_tests(self):
        """create_tables() creates all ORM tables (test-only method)."""
        db = Database("sqlite+aiosqlite:///:memory:")
        await db.init()
        await db.create_tables()

        from sqlalchemy import inspect

        async with db._engine.connect() as conn:
            table_names = await conn.run_sync(lambda c: inspect(c).get_table_names())

        # Should have all tables defined in models
        model_tables = set(Base.metadata.tables.keys())
        assert model_tables.issubset(set(table_names)), (
            f"Missing tables: {model_tables - set(table_names)}"
        )
        await db.close()

    @pytest.mark.asyncio
    async def test_session_requires_init(self):
        db = Database("sqlite+aiosqlite:///:memory:")
        with pytest.raises(RuntimeError, match="not initialised"):
            async with db.session():
                pass

    @pytest.mark.asyncio
    async def test_engine_requires_init(self):
        db = Database("sqlite+aiosqlite:///:memory:")
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = db.engine


class TestRunMigrations:
    @pytest.mark.asyncio
    async def test_run_migrations_inside_event_loop(self):
        """run_migrations() must work from within a running async event loop.

        This was a real bug: the original implementation called
        asyncio.run() inside env.py which fails when there's already
        a running loop.
        """
        db = Database("sqlite+aiosqlite:///./florin.db")
        await db.init()
        # This should not raise "cannot be called from a running event loop"
        await db.run_migrations()
        await db.close()

    @pytest.mark.asyncio
    async def test_run_migrations_is_idempotent(self):
        """Running migrations twice should not error."""
        db = Database("sqlite+aiosqlite:///./florin.db")
        await db.init()
        await db.run_migrations()
        await db.run_migrations()  # second call should be a no-op
        await db.close()


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        async with Database("sqlite+aiosqlite:///:memory:") as db:
            assert db._engine is not None
            await db.create_tables()
            async with db.session() as session:
                assert session is not None
