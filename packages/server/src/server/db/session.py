"""Database session management for Conduit."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from server.db.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine


class Database:
    """
    Async database connection manager.

    Example:
        db = Database(url="postgresql+asyncpg://user:pass@localhost/conduit")
        await db.connect()

        async with db.session() as session:
            result = await session.execute(select(JobHistory))
            jobs = result.scalars().all()

        await db.disconnect()
    """

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
    ) -> None:
        """
        Initialize database connection.

        Args:
            url: Database URL (postgresql+asyncpg://...)
            echo: Enable SQL logging
            pool_size: Connection pool size
            max_overflow: Max connections above pool_size
        """
        self._url = url
        self._echo = echo
        self._pool_size = pool_size
        self._max_overflow = max_overflow

        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        """Get the database engine."""
        if self._engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._engine

    async def connect(self) -> None:
        """Establish database connection and create tables."""
        self._engine = create_async_engine(
            self._url,
            echo=self._echo,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def create_tables(self) -> None:
        """Create all tables (for development/testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        """Drop all tables (for testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        Get a database session.

        Example:
            async with db.session() as session:
                session.add(job)
                await session.commit()
        """
        if self._session_factory is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Global database instance
_database: Database | None = None


def get_database() -> Database:
    """Get the global database instance."""
    if _database is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _database


def init_database(
    url: str,
    **kwargs: Any,
) -> Database:
    """
    Initialize the global database instance.

    Args:
        url: Database URL
        **kwargs: Additional arguments for Database

    Returns:
        Database instance
    """
    global _database
    _database = Database(url, **kwargs)
    return _database
