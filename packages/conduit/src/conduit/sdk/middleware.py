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

from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared.api import API_PREFIX, HOURLY_BUCKET_TTL, MINUTE_BUCKET_TTL, REGISTRY_TTL
from shared.events import API_REQUESTS_STREAM
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def _status_bucket(status: int) -> str:
    if status >= 500:
        return "status_5xx"
    if status >= 400:
        return "status_4xx"
    return "status_2xx"


@dataclass
class ApiTrackingConfig:
    """Controls tracking and event-feed behavior for API request middleware."""

    normalize_paths: bool = True
    registry_refresh_seconds: int = 60
    request_events_enabled: bool = True
    request_events_sample_rate: float = 1.0
    request_events_slow_ms: float = 500.0
    request_events_stream_max_len: int = 50_000


class ApiTrackingMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that writes request metrics and event feed rows to Redis."""

    def __init__(
        self,
        app: Any,
        api_name: str,
        redis_client: Any,
        config: ApiTrackingConfig | None = None,
        api_instance_id: str | None = None,
    ) -> None:
        super().__init__(app)
        self.api_name = api_name
        self.redis = redis_client
        self._config = config or ApiTrackingConfig()
        self._api_instance_id = api_instance_id
        self._last_registry_refresh_monotonic = time.monotonic()
        self._seen_endpoint_keys: set[str] = set()

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000

        try:
            await self._record(
                method=request.method,
                path=self._normalize_path(request),
                status=response.status_code,
                latency_ms=latency_ms,
            )
        except Exception:
            # Never block requests for tracking.
            pass

        return response

    def _normalize_path(self, request: Request) -> str:
        """Prefer route templates (e.g. /users/{id}) to avoid key cardinality blow-up."""
        path = request.url.path
        if not self._config.normalize_paths:
            return path

        route = request.scope.get("route")
        if route is None:
            return path

        route_template = getattr(route, "path_format", None) or getattr(route, "path", None)
        if isinstance(route_template, str) and route_template.startswith("/"):
            return route_template
        return path

    def _should_refresh_registry(self, endpoint_key: str, now_monotonic: float) -> bool:
        if endpoint_key not in self._seen_endpoint_keys:
            self._seen_endpoint_keys.add(endpoint_key)
            self._last_registry_refresh_monotonic = now_monotonic
            return True

        refresh_seconds = max(self._config.registry_refresh_seconds, 0)
        if refresh_seconds <= 0:
            return False

        elapsed = now_monotonic - self._last_registry_refresh_monotonic
        if elapsed >= refresh_seconds:
            self._last_registry_refresh_monotonic = now_monotonic
            return True
        return False

    def _build_request_event(
        self,
        *,
        method: str,
        path: str,
        status: int,
        latency_ms: float,
        at: datetime,
    ) -> dict[str, Any] | None:
        if not self._config.request_events_enabled:
            return None

        is_error = status >= 400
        is_slow = latency_ms >= max(self._config.request_events_slow_ms, 0.0)
        sample_rate = min(max(self._config.request_events_sample_rate, 0.0), 1.0)

        sampled = False
        if not is_error and not is_slow:
            if sample_rate <= 0.0:
                return None
            if sample_rate < 1.0 and random.random() > sample_rate:
                return None
            sampled = sample_rate < 1.0

        return {
            "id": uuid.uuid4().hex,
            "at": at.isoformat(),
            "api_name": self.api_name,
            "method": method.upper(),
            "path": path,
            "status": status,
            "latency_ms": round(latency_ms, 2),
            "instance_id": self._api_instance_id,
            "sampled": sampled,
        }

    async def _record(
        self,
        method: str,
        path: str,
        status: int,
        latency_ms: float,
    ) -> None:
        now = datetime.now(UTC)
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        hour_key = now.strftime("%Y-%m-%dT%H")
        endpoint_key = f"{method.upper()}:{path}"

        minute_hash = f"{API_PREFIX}:{self.api_name}:{endpoint_key}:m:{minute_key}"
        hourly_hash = f"{API_PREFIX}:{self.api_name}:{endpoint_key}:h:{hour_key}"
        registry_key = f"{API_PREFIX}:registry"
        endpoints_key = f"{API_PREFIX}:{self.api_name}:endpoints"

        status_field = _status_bucket(status)
        is_error = 1 if status >= 400 else 0
        now_monotonic = time.monotonic()

        pipe = self.redis.pipeline(transaction=False)

        if self._should_refresh_registry(endpoint_key, now_monotonic):
            pipe.sadd(registry_key, self.api_name)
            pipe.expire(registry_key, REGISTRY_TTL)
            pipe.sadd(endpoints_key, endpoint_key)
            pipe.expire(endpoints_key, REGISTRY_TTL)

        pipe.hincrby(minute_hash, "requests", 1)
        pipe.hincrby(minute_hash, "errors", is_error)
        pipe.hincrbyfloat(minute_hash, "total_latency_ms", round(latency_ms, 2))
        pipe.hincrby(minute_hash, status_field, 1)
        pipe.expire(minute_hash, MINUTE_BUCKET_TTL)

        pipe.hincrby(hourly_hash, "requests", 1)
        pipe.hincrby(hourly_hash, "errors", is_error)
        pipe.hincrbyfloat(hourly_hash, "total_latency_ms", round(latency_ms, 2))
        pipe.hincrby(hourly_hash, status_field, 1)
        pipe.expire(hourly_hash, HOURLY_BUCKET_TTL)

        await pipe.execute()

        request_event = self._build_request_event(
            method=method,
            path=path,
            status=status,
            latency_ms=latency_ms,
            at=now,
        )
        if not request_event:
            return

        stream_payload = {
            "type": "api.request",
            "api_name": self.api_name,
            "method": method.upper(),
            "path": path,
            "status": str(status),
            "at": now.isoformat(),
            "data": json.dumps(request_event, default=str),
        }
        try:
            await self.redis.xadd(
                API_REQUESTS_STREAM,
                stream_payload,
                maxlen=max(self._config.request_events_stream_max_len, 100),
                approximate=True,
            )
        except TypeError:
            await self.redis.xadd(
                API_REQUESTS_STREAM,
                stream_payload,
                maxlen=max(self._config.request_events_stream_max_len, 100),
            )
