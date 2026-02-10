from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from fakeredis.aioredis import FakeRedis


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()
