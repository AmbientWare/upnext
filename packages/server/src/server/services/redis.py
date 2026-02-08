"""Redis service for API."""

import redis.asyncio as redis

# Redis client singleton
_redis_client: redis.Redis | None = None


async def connect_redis(url: str) -> redis.Redis:
    """
    Connect to Redis and return the client.

    Call this during startup to initialize the connection.
    The client is stored as a singleton for get_redis() access.

    Args:
        url: Redis URL.

    Returns:
        Connected Redis client
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


async def get_redis() -> redis.Redis:
    """
    Get the Redis client.

    Raises RuntimeError if connect_redis() hasn't been called.
    Use this after startup to access the shared client.
    """
    if _redis_client is None:
        raise RuntimeError("Redis not connected. Call connect_redis() first.")
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
