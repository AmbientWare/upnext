"""High-level backend service with session-scoped repositories."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

from server.backends.base import BaseBackend
from server.backends.factory import (
    PersistenceRuntime,
    get_backend_runtime,
    init_backend,
)
from server.backends.session_context import RepositorySession
from server.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class BackendService:
    """Service object exposing configured persistence backend repositories."""

    def __init__(self) -> None:
        self._connected = False

    async def connect(self) -> PersistenceRuntime:
        settings = get_settings()
        runtime = init_backend(
            backend=settings.backend,
            database_url=settings.effective_database_url,
            redis_url=settings.redis_url,
        )
        if not self._connected:
            await runtime.backend.connect()
            self._connected = True
        return runtime

    async def disconnect(self) -> None:
        if not self._connected:
            return
        runtime = get_backend_runtime()
        await runtime.backend.disconnect()
        self._connected = False

    @property
    def runtime(self) -> PersistenceRuntime:
        return get_backend_runtime()

    @property
    def backend(self) -> BaseBackend:
        return self.runtime.backend

    @property
    def backend_name(self) -> str:
        return self.backend.backend_name

    @property
    def is_initialized(self) -> bool:
        return self._connected

    async def prepare_startup(self, required_tables: set[str]) -> None:
        await self.backend.prepare_startup(required_tables)

    async def check_readiness(self) -> None:
        await self.backend.check_readiness()

    def bind_session(self, raw_session: object) -> RepositorySession:
        if isinstance(raw_session, RepositorySession):
            return raw_session
        backend = self.runtime.backend
        return RepositorySession(
            raw_session=raw_session,
            jobs=backend.job_repository(raw_session),
            artifacts=backend.artifact_repository(raw_session),
            auth=backend.auth_repository(raw_session),
            secrets=backend.secrets_repository(raw_session),
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[RepositorySession]:
        async with self.runtime.backend.session() as session:
            yield self.bind_session(session)


@lru_cache(maxsize=1)
def _get_backend_service() -> BackendService:
    return BackendService()


def get_backend(*, initialized: bool = True) -> BackendService:
    backend = _get_backend_service()
    if initialized and not backend.is_initialized:
        raise RuntimeError("Backend not initialized. Call connect() first.")
    return backend


def reset_backend_service() -> None:
    _get_backend_service.cache_clear()
