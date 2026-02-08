from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from server.db.session import Database
from server.db.session import init_database as _init_database
import server.db.session as session_module


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def sqlite_db(tmp_path: Path) -> AsyncIterator[Database]:
    db_path = tmp_path / "server-test.db"
    db = _init_database(f"sqlite+aiosqlite:///{db_path}")
    await db.connect()
    await db.create_tables()
    try:
        yield db
    finally:
        await db.disconnect()
        session_module._database = None  # type: ignore[attr-defined]
