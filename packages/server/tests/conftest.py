from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Generator

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from server.backends import reset_backend_runtime, reset_backend_service
from server.backends.sql.base import BaseSqlBackend
from server.routes.jobs.jobs_stream import clear_trends_cache
from server.runtime_scope import AuthScope, RuntimeModes, RuntimeRoles


@pytest.fixture(autouse=True)
def _clear_trends_cache() -> Generator[Any, Any, Any]:
    """Clear the module-level trends snapshot cache between tests."""
    clear_trends_cache()
    reset_backend_service()
    reset_backend_runtime()
    yield  # type: ignore[misc]
    clear_trends_cache()
    reset_backend_service()
    reset_backend_runtime()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def sqlite_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[BaseSqlBackend]:
    db_path = tmp_path / "server-test.db"
    db = BaseSqlBackend(f"sqlite+aiosqlite:///{db_path}")
    await db.connect()
    await db.create_tables()
    import server.routes.jobs.jobs_stream as jobs_stream_module
    import server.services.events.processing as event_processing_module
    import server.services.events.subscriber as event_subscriber_module
    import server.services.operations.cleanup as cleanup_module

    monkeypatch.setattr(event_processing_module, "get_backend", lambda: db)
    monkeypatch.setattr(event_subscriber_module, "get_backend", lambda: db)
    monkeypatch.setattr(jobs_stream_module, "get_backend", lambda: db)
    monkeypatch.setattr(cleanup_module, "get_backend", lambda: db)
    try:
        yield db
    finally:
        await db.disconnect()


@pytest.fixture
def local_auth_scope() -> AuthScope:
    return AuthScope(
        deployment_id="local",
        workspace_id=None,
        role=RuntimeRoles.ADMIN,
        mode=RuntimeModes.SELF_HOSTED,
        subject="test-admin",
    )
