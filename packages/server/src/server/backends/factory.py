"""Persistence backend selection and repository factory."""

from __future__ import annotations

from dataclasses import dataclass

from server.backends.base import BaseBackend
from server.backends.redis.session import RedisBackend
from server.backends.sql.postgres import PostgresSqlBackend
from server.backends.sql.sqlite import SqliteSqlBackend
from server.backends.types import PersistenceBackends

PersistenceBackend = PersistenceBackends


@dataclass(frozen=True)
class PersistenceRuntime:
    backend_type: PersistenceBackends
    backend: BaseBackend


_runtime: PersistenceRuntime | None = None


def reset_backend_runtime() -> None:
    """Reset in-memory backend runtime reference (primarily for tests)."""
    global _runtime
    _runtime = None


def init_backend(
    *,
    backend: PersistenceBackends,
    database_url: str | None,
    redis_url: str | None,
) -> PersistenceRuntime:
    global _runtime
    if _runtime is not None:
        if _runtime.backend_type != backend:
            raise RuntimeError(
                "Persistence backend already initialized as "
                f"{_runtime.backend_type.value}; cannot switch to {backend.value} "
                "without process restart."
            )
        return _runtime

    if backend == PersistenceBackends.REDIS:
        if not redis_url:
            raise RuntimeError("UPNEXT_BACKEND=redis requires UPNEXT_REDIS_URL.")
        backend_impl = RedisBackend(redis_url)
        _runtime = PersistenceRuntime(backend_type=backend, backend=backend_impl)
        return _runtime

    if backend == PersistenceBackends.POSTGRES:
        if not database_url:
            raise RuntimeError("UPNEXT_BACKEND=postgres requires UPNEXT_DATABASE_URL.")
        backend_impl = PostgresSqlBackend(database_url)
        _runtime = PersistenceRuntime(backend_type=backend, backend=backend_impl)
        return _runtime

    # sqlite
    backend_impl = SqliteSqlBackend(database_url or "sqlite+aiosqlite:///upnext.db")
    _runtime = PersistenceRuntime(backend_type=backend, backend=backend_impl)
    return _runtime


def get_backend_runtime() -> PersistenceRuntime:
    if _runtime is None:
        raise RuntimeError("Backend not initialized. Call init_backend() first.")
    return _runtime
