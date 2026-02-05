"""Redis service for API."""

import os

import redis.asyncio as redis

# Redis client (initialized lazily)
_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get async Redis client, initialize if needed."""
    global _redis_client
    if _redis_client is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
