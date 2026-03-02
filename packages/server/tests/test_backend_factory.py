from __future__ import annotations

import pytest
from server.backends.factory import init_backend, reset_backend_runtime
from server.backends.types import PersistenceBackends


@pytest.fixture(autouse=True)
def _reset_backend_runtime() -> None:
    reset_backend_runtime()
    yield
    reset_backend_runtime()


@pytest.mark.parametrize(
    ("backend", "database_url", "redis_url", "expected_name"),
    [
        (PersistenceBackends.REDIS, None, "redis://localhost:6379", "redis"),
        (
            PersistenceBackends.POSTGRES,
            "postgresql+asyncpg://user:pass@localhost/upnext",
            None,
            "postgres",
        ),
        (PersistenceBackends.SQLITE, None, None, "sqlite"),
    ],
)
def test_init_backend_returns_expected_runtime(
    backend: PersistenceBackends,
    database_url: str | None,
    redis_url: str | None,
    expected_name: str,
) -> None:
    runtime = init_backend(
        backend=backend,
        database_url=database_url,
        redis_url=redis_url,
    )
    assert runtime.backend_type == backend
    assert runtime.backend.backend_name == expected_name


@pytest.mark.parametrize(
    ("backend", "database_url", "redis_url", "expected_error"),
    [
        (
            PersistenceBackends.REDIS,
            None,
            None,
            "UPNEXT_BACKEND=redis requires UPNEXT_REDIS_URL.",
        ),
        (
            PersistenceBackends.POSTGRES,
            None,
            None,
            "UPNEXT_BACKEND=postgres requires UPNEXT_DATABASE_URL.",
        ),
    ],
)
def test_init_backend_validates_required_backend_urls(
    backend: PersistenceBackends,
    database_url: str | None,
    redis_url: str | None,
    expected_error: str,
) -> None:
    with pytest.raises(RuntimeError, match=expected_error):
        init_backend(
            backend=backend,
            database_url=database_url,
            redis_url=redis_url,
        )


def test_init_backend_disallows_switching_backend_without_restart() -> None:
    init_backend(
        backend=PersistenceBackends.REDIS,
        database_url=None,
        redis_url="redis://localhost:6379",
    )
    with pytest.raises(RuntimeError, match="cannot switch"):
        init_backend(
            backend=PersistenceBackends.SQLITE,
            database_url=None,
            redis_url=None,
        )
