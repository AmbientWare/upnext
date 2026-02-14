"""Shared SSE streaming constants."""

# Redis XREAD/XREADGROUP block timeout in milliseconds.
# Controls keep-alive interval — clients get a keep-alive comment after this timeout.
SSE_BLOCK_MS: int = 15_000

# Redis pubsub poll timeout in seconds (for SUBSCRIBE-based streams).
SSE_PUBSUB_TIMEOUT_SECONDS: float = 15.0

# Default number of entries to read per XREAD/XRANGE batch.
SSE_READ_COUNT: int = 200

# Snapshot cache TTL in seconds. Prevents thundering herd on concurrent SSE clients.
SSE_CACHE_TTL_SECONDS: float = 0.75

# Hard cap on snapshot cache entries before full eviction.
SSE_CACHE_MAX_SIZE: int = 256

# Common SSE response headers.
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
