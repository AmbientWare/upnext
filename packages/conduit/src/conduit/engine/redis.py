"""Redis client factory for Conduit."""

import redis.asyncio as aioredis


def create_redis_client(url: str) -> aioredis.Redis:
    """Create an async Redis client from a URL."""
    return aioredis.from_url(url, decode_responses=False)
