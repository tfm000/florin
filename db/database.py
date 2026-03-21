"""
Database engine, session factory, and lifecycle management.

Uses SQLAlchemy 2.0 async with aiosqlite for zero-config local storage.

Usage:
    db = Database("sqlite+aiosqlite:///./sentinel.db")
    await db.init()
    
    async with db.session() as session:
        session.add(trade)
        await session.commit()
    
    await db.close()
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base

logger = logging.getLogger(__name__)


class Database:
    """Async database connection manager."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def init(self) -> None:
        """Create engine and session factory.

        Does NOT create tables — schema is managed exclusively by Alembic.
        Run ``alembic upgrade head`` (or call :meth:`run_migrations`) to
        apply pending migrations.
        """
        logger.info("Initialising database: %s", self._url)

        self._engine = create_async_engine(
            self._url,
            echo=False,
            pool_pre_ping=True,
            # SQLite-specific: enable WAL mode for concurrent reads
            connect_args={"check_same_thread": False} if "sqlite" in self._url else {},
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info("Database engine initialised")

    async def create_tables(self) -> None:
        """Create all tables from ORM metadata.

        For **tests only** — production code should use :meth:`run_migrations`
        so that Alembic tracks schema history.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def run_migrations(self) -> None:
        """Run pending Alembic migrations (``upgrade head``).

        Called during application startup so the schema is always up
        to date without requiring a separate ``alembic`` CLI step.
        """
        from alembic.config import Config
        from alembic import command

        def _run(connection):
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")

        async with self._engine.begin() as conn:
            await conn.run_sync(_run)

        logger.info("Database migrations applied")

    async def close(self) -> None:
        """Dispose of the engine and all connections."""
        if self._engine:
            await self._engine.dispose()
            logger.info("Database connections closed")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        Provide a transactional async session scope.
        
        Usage:
            async with db.session() as session:
                session.add(obj)
                await session.commit()
        """
        if self._session_factory is None:
            raise RuntimeError("Database not initialised — call .init() first")

        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not initialised — call .init() first")
        return self._engine

    async def __aenter__(self) -> Database:
        await self.init()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
