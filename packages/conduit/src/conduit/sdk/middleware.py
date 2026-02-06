"""API request tracking middleware.

Tracks request metrics using Redis hash buckets at two granularities:
- Minute buckets (TTL 10min) for real-time req/min
- Hourly buckets (TTL 30 days) for trends/history

Writes are per-endpoint. The server aggregates up to API level when reading.

Redis key structure:
    conduit:api:registry                                    → SET of api names
    conduit:api:{api}:endpoints                             → SET of "METHOD:path"
    conduit:api:{api}:{method}:{path}:m:{YYYY-MM-DDTHH:MM} → HASH (minute bucket)
    conduit:api:{api}:{method}:{path}:h:{YYYY-MM-DDTHH}    → HASH (hourly bucket)

Each hash contains:
    requests, errors, total_latency_ms, status_2xx, status_4xx, status_5xx
"""

import time
from datetime import UTC, datetime

from shared.api import API_PREFIX, HOURLY_BUCKET_TTL, MINUTE_BUCKET_TTL, REGISTRY_TTL
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def _status_bucket(status: int) -> str:
    if status >= 500:
        return "status_5xx"
    elif status >= 400:
        return "status_4xx"
    return "status_2xx"


class ApiTrackingMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that writes request metrics to Redis hash buckets."""

    def __init__(self, app, api_name: str, redis_client):  # type: ignore
        super().__init__(app)
        self.api_name = api_name
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next):  # type: ignore
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000

        try:
            await self._record(
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                latency_ms=latency_ms,
            )
        except Exception:
            pass  # Never block requests for tracking

        return response

    async def _record(
        self, method: str, path: str, status: int, latency_ms: float
    ) -> None:
        now = datetime.now(UTC)
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        hour_key = now.strftime("%Y-%m-%dT%H")
        ep_key = f"{method}:{path}"

        minute_hash = f"{API_PREFIX}:{self.api_name}:{ep_key}:m:{minute_key}"
        hourly_hash = f"{API_PREFIX}:{self.api_name}:{ep_key}:h:{hour_key}"
        registry_key = f"{API_PREFIX}:registry"
        endpoints_key = f"{API_PREFIX}:{self.api_name}:endpoints"

        status_field = _status_bucket(status)
        is_error = 1 if status >= 400 else 0

        pipe = self.redis.pipeline(transaction=False)

        # Registry
        pipe.sadd(registry_key, self.api_name)
        pipe.expire(registry_key, REGISTRY_TTL)
        pipe.sadd(endpoints_key, ep_key)
        pipe.expire(endpoints_key, REGISTRY_TTL)

        # Minute bucket
        pipe.hincrby(minute_hash, "requests", 1)
        pipe.hincrby(minute_hash, "errors", is_error)
        pipe.hincrbyfloat(minute_hash, "total_latency_ms", round(latency_ms, 2))
        pipe.hincrby(minute_hash, status_field, 1)
        pipe.expire(minute_hash, MINUTE_BUCKET_TTL)

        # Hourly bucket
        pipe.hincrby(hourly_hash, "requests", 1)
        pipe.hincrby(hourly_hash, "errors", is_error)
        pipe.hincrbyfloat(hourly_hash, "total_latency_ms", round(latency_ms, 2))
        pipe.hincrby(hourly_hash, status_field, 1)
        pipe.expire(hourly_hash, HOURLY_BUCKET_TTL)

        await pipe.execute()
