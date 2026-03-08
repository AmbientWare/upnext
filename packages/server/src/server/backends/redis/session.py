"""Redis persistence backend implementation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import redis.asyncio as redis

from server.backends.base import BaseBackend
from server.backends.base.repositories import (
    BaseArtifactRepository,
    BaseJobRepository,
)
from server.backends.redis.repositories import (
    RedisArtifactRepository,
    RedisJobRepository,
)
from server.backends.session_context import RepositorySession
from server.backends.types import PersistenceBackends

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass
class RedisSession:
    redis: redis.Redis

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


def require_redis_client(session: object) -> redis.Redis:
    redis_client = getattr(session, PersistenceBackends.REDIS.value, None)
    if redis_client is None:
        raise RuntimeError("Redis session missing redis client.")
    return redis_client


class RedisBackend(BaseBackend):
    backend_name = PersistenceBackends.REDIS.value

    def __init__(self, url: str) -> None:
        self._url = url
        self._redis: redis.Redis | None = None

    @property
    def is_initialized(self) -> bool:
        return self._redis is not None

    @property
    def redis(self) -> redis.Redis:
        if self._redis is None:
            raise RuntimeError("Redis persistence not connected. Call connect() first.")
        return self._redis

    async def connect(self) -> None:
        self._redis = redis.from_url(self._url, decode_responses=True)
        await self._redis.ping()  # type: ignore[attr-defined]

    async def disconnect(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def create_tables(self) -> None:
        return None

    async def drop_tables(self) -> None:
        return None

    async def get_missing_tables(self, required_tables: set[str]) -> list[str]:
        _ = required_tables
        return []

    async def prepare_startup(self, required_tables: set[str]) -> None:
        _ = required_tables
        return None

    async def check_readiness(self) -> None:
        await self.redis.ping()  # type: ignore[attr-defined]

    @asynccontextmanager
    async def session(self) -> AsyncIterator[RepositorySession]:
        raw_session = RedisSession(redis=self.redis)
        yield RepositorySession(
            raw_session=raw_session,
            jobs=self.job_repository(raw_session),
            artifacts=self.artifact_repository(raw_session),
        )

    def job_repository(self, session: object) -> BaseJobRepository:
        return RedisJobRepository(require_redis_client(session))

    def artifact_repository(self, session: object) -> BaseArtifactRepository:
        return RedisArtifactRepository(require_redis_client(session))
