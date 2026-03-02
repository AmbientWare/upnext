"""Shared SQL backend base implementation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from server.backends.base import BaseBackend
from server.backends.base.repositories import (
    BaseArtifactRepository,
    BaseAuthRepository,
    BaseJobRepository,
    BaseSecretsRepository,
)
from server.backends.session_context import RepositorySession
from server.backends.sql.shared.repositories import (
    PostgresArtifactRepository,
    PostgresAuthRepository,
    PostgresJobRepository,
    PostgresSecretsRepository,
)
from server.backends.sql.shared.session import Database as SqlDatabase

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def require_sql_session(session: object) -> AsyncSession:
    if not isinstance(session, AsyncSession):
        raise RuntimeError("SQL backend session is not an AsyncSession.")
    return session


class BaseSqlBackend(BaseBackend):
    """Shared SQL backend wrapper used by PostgreSQL and SQLite backends."""

    backend_name: str = "sql"

    def __init__(self, database_url: str) -> None:
        self._database = SqlDatabase(database_url)
        self._is_connected = False

    @property
    def database(self) -> SqlDatabase:
        return self._database

    @property
    def is_initialized(self) -> bool:
        return self._is_connected

    async def connect(self) -> None:
        await self._database.connect()
        self._is_connected = True

    async def disconnect(self) -> None:
        await self._database.disconnect()
        self._is_connected = False

    async def create_tables(self) -> None:
        await self._database.create_tables()

    async def drop_tables(self) -> None:
        await self._database.drop_tables()

    async def get_missing_tables(self, required_tables: set[str]) -> list[str]:
        return await self._database.get_missing_tables(required_tables)

    async def prepare_startup(self, required_tables: set[str]) -> None:
        missing_tables = await self.get_missing_tables(required_tables)
        if missing_tables:
            raise RuntimeError(
                "Database schema is missing required tables: "
                + ", ".join(missing_tables)
                + ". Run Alembic migrations (e.g. `alembic upgrade head`) before starting."
            )

    async def check_readiness(self) -> None:
        async with self._database.session() as session:
            await session.execute(text("SELECT 1"))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[RepositorySession]:
        async with self._database.session() as raw_session:
            yield RepositorySession(
                raw_session=raw_session,
                jobs=self.job_repository(raw_session),
                artifacts=self.artifact_repository(raw_session),
                auth=self.auth_repository(raw_session),
                secrets=self.secrets_repository(raw_session),
            )

    def job_repository(self, session: object) -> BaseJobRepository:
        return PostgresJobRepository(require_sql_session(session))

    def artifact_repository(self, session: object) -> BaseArtifactRepository:
        return PostgresArtifactRepository(require_sql_session(session))

    def auth_repository(self, session: object) -> BaseAuthRepository:
        return PostgresAuthRepository(require_sql_session(session))

    def secrets_repository(self, session: object) -> BaseSecretsRepository:
        return PostgresSecretsRepository(require_sql_session(session))
