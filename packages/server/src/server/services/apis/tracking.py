"""API metrics reader - reads time-bucketed metrics from Redis.

The SDK middleware writes per-endpoint metrics to Redis hash buckets:
- Minute buckets (TTL 10min) for real-time req/min
- Hourly buckets (TTL 30 days) for trends/history

This module reads and aggregates those buckets for the API routes.

Redis key structure (written by upnext.sdk.middleware):
    upnext:api:registry                                    -> SET of api names
    upnext:api:{api}:endpoints                             -> SET of "METHOD:path"
    upnext:api:{api}:{method}:{path}:m:{YYYY-MM-DDTHH:MM} -> HASH (minute)
    upnext:api:{api}:{method}:{path}:h:{YYYY-MM-DDTHH}    -> HASH (hourly)
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shared.keys import (
    api_endpoints_key,
    api_hourly_bucket_key,
    api_minute_bucket_key,
    api_registry_key,
)

from server.services.apis.tracking_models import (
    ApiEndpointMetrics,
    ApiHourlyTrend,
    ApiMetricsByName,
    ApiMetricsSummary,
)
from server.services.redis import get_redis

logger = logging.getLogger(__name__)


class _ApiBucket(BaseModel):
    """Typed Redis hash payload for API metrics buckets."""

    model_config = ConfigDict(extra="ignore")

    requests: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    total_latency_ms: float = Field(default=0.0, ge=0)
    status_2xx: int = Field(default=0, ge=0)
    status_4xx: int = Field(default=0, ge=0)
    status_5xx: int = Field(default=0, ge=0)


class _IntMetric(BaseModel):
    """Typed scalar used for single integer bucket reads."""

    value: int = Field(ge=0)


@dataclass
class _HourlyTotals:
    """Internal accumulator for bucket totals."""

    requests: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0
    status_2xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0


class ApiMetricsReader:
    """Reads API metrics from Redis hash buckets."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    @staticmethod
    def _decode_text(value: object) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode()
            except UnicodeDecodeError:
                return None
        return None

    def _decode_members(self, raw_values: object) -> list[str]:
        if not isinstance(raw_values, set | list | tuple):
            return []

        values: list[str] = []
        for raw_value in raw_values:
            value = self._decode_text(raw_value)
            if value and value.strip():
                values.append(value)
        return values

    def _normalize_mapping(self, raw_value: object) -> dict[str, object] | None:
        if not isinstance(raw_value, Mapping):
            return None

        normalized: dict[str, object] = {}
        for raw_key, raw_item in raw_value.items():
            key = self._decode_text(raw_key)
            if not key:
                continue
            if isinstance(raw_item, bytes):
                try:
                    normalized[key] = raw_item.decode()
                except UnicodeDecodeError:
                    continue
            else:
                normalized[key] = raw_item
        return normalized

    def _parse_bucket(self, raw_bucket: object) -> _ApiBucket | None:
        normalized = self._normalize_mapping(raw_bucket)
        if normalized is None:
            return None
        try:
            return _ApiBucket.model_validate(normalized)
        except ValidationError:
            return None

    def _parse_non_negative_int(self, raw_value: object) -> int | None:
        if isinstance(raw_value, bytes):
            try:
                raw_value = raw_value.decode()
            except UnicodeDecodeError:
                return None
        try:
            return _IntMetric.model_validate({"value": raw_value}).value
        except ValidationError:
            return None

    async def get_apis(self) -> list[ApiMetricsByName]:
        """Get metrics aggregated by API name (sum of last 24h hourly buckets)."""
        raw_api_names = await self._redis.smembers(api_registry_key())
        api_names = self._decode_members(raw_api_names)
        if not api_names:
            return []

        results: list[ApiMetricsByName] = []
        for api_name in api_names:
            endpoint_values = await self._redis.smembers(api_endpoints_key(api_name))
            endpoint_keys = self._decode_members(endpoint_values)
            if not endpoint_keys:
                continue

            totals = await self._aggregate_hourly(api_name, endpoint_keys, hours=24)
            if totals.requests == 0:
                continue

            results.append(
                ApiMetricsByName(
                    name=api_name,
                    endpoint_count=len(endpoint_keys),
                    requests_24h=totals.requests,
                    avg_latency_ms=round(
                        totals.total_latency_ms / totals.requests,
                        2,
                    ),
                    error_rate=round(totals.errors / totals.requests * 100, 1),
                    requests_per_min=await self._get_req_per_min(
                        api_name, endpoint_keys
                    ),
                )
            )

        results.sort(key=lambda item: item.requests_24h, reverse=True)
        return results

    async def get_endpoints(
        self, api_name: str | None = None
    ) -> list[ApiEndpointMetrics]:
        """Get per-endpoint metrics. Optionally filter by API name."""
        if api_name:
            api_names = [api_name]
        else:
            raw_api_names = await self._redis.smembers(api_registry_key()) or set()
            api_names = self._decode_members(raw_api_names)

        results: list[ApiEndpointMetrics] = []
        for name in api_names:
            endpoint_values = await self._redis.smembers(api_endpoints_key(name))
            endpoint_keys = self._decode_members(endpoint_values)
            if not endpoint_keys:
                continue

            for ep_key in endpoint_keys:
                parts = ep_key.split(":", 1)
                if len(parts) != 2:
                    continue
                method, path = parts

                totals = await self._aggregate_hourly(name, [ep_key], hours=24)
                if totals.requests == 0:
                    continue

                requests = totals.requests
                status_2xx = totals.status_2xx
                status_4xx = totals.status_4xx
                status_5xx = totals.status_5xx
                errors = totals.errors

                results.append(
                    ApiEndpointMetrics(
                        api_name=name,
                        method=method,
                        path=path,
                        requests_24h=requests,
                        requests_per_min=await self._get_req_per_min(name, [ep_key]),
                        avg_latency_ms=round(totals.total_latency_ms / requests, 2),
                        error_rate=round(errors / requests * 100, 1),
                        success_rate=round(status_2xx / requests * 100, 1),
                        client_error_rate=round(status_4xx / requests * 100, 1),
                        server_error_rate=round(status_5xx / requests * 100, 1),
                        status_2xx=status_2xx,
                        status_4xx=status_4xx,
                        status_5xx=status_5xx,
                    )
                )

        results.sort(key=lambda item: item.requests_24h, reverse=True)
        return results

    async def get_hourly_trends(self, hours: int = 24) -> list[ApiHourlyTrend]:
        """Get hourly trend data across all APIs for charts."""
        now = datetime.now(UTC)

        raw_api_names = await self._redis.smembers(api_registry_key()) or set()
        all_endpoints: list[tuple[str, str]] = []
        for api_name in self._decode_members(raw_api_names):
            endpoint_values = (
                await self._redis.smembers(api_endpoints_key(api_name)) or set()
            )
            for endpoint_value in self._decode_members(endpoint_values):
                all_endpoints.append((api_name, endpoint_value))

        result: list[ApiHourlyTrend] = []
        for i in range(hours):
            hour_dt = now - timedelta(hours=hours - i - 1)
            hour_key = hour_dt.strftime("%Y-%m-%dT%H")
            hour_label = hour_dt.strftime("%Y-%m-%dT%H:00:00Z")

            s2xx = 0
            s4xx = 0
            s5xx = 0

            if all_endpoints:
                pipe = self._redis.pipeline(transaction=False)
                for api_name, ep_key in all_endpoints:
                    pipe.hgetall(api_hourly_bucket_key(api_name, ep_key, hour_key))
                bucket_results = await pipe.execute()

                for raw_bucket in bucket_results:
                    bucket = self._parse_bucket(raw_bucket)
                    if bucket is None:
                        continue
                    s2xx += bucket.status_2xx
                    s4xx += bucket.status_4xx
                    s5xx += bucket.status_5xx

            result.append(
                ApiHourlyTrend(
                    hour=hour_label,
                    success_2xx=s2xx,
                    client_4xx=s4xx,
                    server_5xx=s5xx,
                )
            )

        return result

    async def get_summary(self) -> ApiMetricsSummary:
        """Get summary stats for the dashboard."""
        apis = await self.get_apis()

        total_requests = sum(item.requests_24h for item in apis)
        total_latency = sum(item.avg_latency_ms * item.requests_24h for item in apis)
        total_errors = sum(item.error_rate / 100 * item.requests_24h for item in apis)

        if total_requests == 0:
            return ApiMetricsSummary(
                requests_24h=0,
                avg_latency_ms=0.0,
                error_rate=0.0,
            )

        return ApiMetricsSummary(
            requests_24h=total_requests,
            avg_latency_ms=round(total_latency / total_requests, 2),
            error_rate=round(total_errors / total_requests * 100, 1),
        )

    async def get_summary_window(self, *, minutes: int) -> ApiMetricsSummary:
        """Get summary stats for a rolling window in minutes."""
        safe_minutes = max(1, int(minutes))

        if safe_minutes >= 24 * 60:
            return await self.get_summary()

        endpoints_by_api = await self._list_endpoints_by_api()
        if not endpoints_by_api:
            return ApiMetricsSummary(
                requests_24h=0,
                avg_latency_ms=0.0,
                error_rate=0.0,
            )

        totals = _HourlyTotals()
        for api_name, endpoint_keys in endpoints_by_api:
            api_totals = await self._aggregate_minutes(
                api_name,
                endpoint_keys,
                minutes=safe_minutes,
            )
            totals.requests += api_totals.requests
            totals.errors += api_totals.errors
            totals.total_latency_ms += api_totals.total_latency_ms

        if totals.requests <= 0:
            return ApiMetricsSummary(
                requests_24h=0,
                avg_latency_ms=0.0,
                error_rate=0.0,
            )

        return ApiMetricsSummary(
            requests_24h=totals.requests,
            avg_latency_ms=round(totals.total_latency_ms / totals.requests, 2),
            error_rate=round(totals.errors / totals.requests * 100, 1),
        )

    async def _aggregate_hourly(
        self,
        api_name: str,
        endpoints: Sequence[str],
        hours: int = 24,
    ) -> _HourlyTotals:
        """Sum hourly buckets for the given endpoints over N hours."""
        if not endpoints:
            return _HourlyTotals()

        now = datetime.now(UTC)
        hour_keys = [
            (now - timedelta(hours=hours - i - 1)).strftime("%Y-%m-%dT%H")
            for i in range(hours)
        ]

        totals = _HourlyTotals()

        pipe = self._redis.pipeline(transaction=False)
        for ep_key in endpoints:
            for hour_key in hour_keys:
                pipe.hgetall(api_hourly_bucket_key(api_name, ep_key, hour_key))

        results = await pipe.execute()

        for raw_bucket in results:
            bucket = self._parse_bucket(raw_bucket)
            if bucket is None:
                continue
            totals.requests += bucket.requests
            totals.errors += bucket.errors
            totals.total_latency_ms += bucket.total_latency_ms
            totals.status_2xx += bucket.status_2xx
            totals.status_4xx += bucket.status_4xx
            totals.status_5xx += bucket.status_5xx

        return totals

    async def _aggregate_minutes(
        self,
        api_name: str,
        endpoints: Sequence[str],
        *,
        minutes: int,
    ) -> _HourlyTotals:
        """Sum minute buckets for the given endpoints over N recent minutes."""
        if not endpoints:
            return _HourlyTotals()

        safe_minutes = max(1, int(minutes))
        now = datetime.now(UTC)
        minute_keys = [
            (now - timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M")
            for i in range(safe_minutes)
        ]

        totals = _HourlyTotals()

        pipe = self._redis.pipeline(transaction=False)
        for ep_key in endpoints:
            for minute_key in minute_keys:
                pipe.hgetall(api_minute_bucket_key(api_name, ep_key, minute_key))

        results = await pipe.execute()
        for raw_bucket in results:
            bucket = self._parse_bucket(raw_bucket)
            if bucket is None:
                continue
            totals.requests += bucket.requests
            totals.errors += bucket.errors
            totals.total_latency_ms += bucket.total_latency_ms
            totals.status_2xx += bucket.status_2xx
            totals.status_4xx += bucket.status_4xx
            totals.status_5xx += bucket.status_5xx

        return totals

    async def _list_endpoints_by_api(self) -> list[tuple[str, list[str]]]:
        raw_api_names = await self._redis.smembers(api_registry_key())
        api_names = self._decode_members(raw_api_names)
        if not api_names:
            return []

        endpoints_by_api: list[tuple[str, list[str]]] = []
        for api_name in api_names:
            endpoint_values = await self._redis.smembers(api_endpoints_key(api_name))
            endpoint_keys = self._decode_members(endpoint_values)
            if endpoint_keys:
                endpoints_by_api.append((api_name, endpoint_keys))

        return endpoints_by_api

    async def _get_req_per_min(self, api_name: str, endpoints: Sequence[str]) -> float:
        """Get current requests/min from the latest minute bucket."""
        if not endpoints:
            return 0.0

        now = datetime.now(UTC)
        minute_keys = [
            (now - timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M") for i in range(1, 3)
        ]

        pipe = self._redis.pipeline(transaction=False)
        for ep_key in endpoints:
            for minute_key in minute_keys:
                pipe.hget(
                    api_minute_bucket_key(api_name, ep_key, minute_key), "requests"
                )

        results = await pipe.execute()

        total = 0
        for raw_value in results:
            if raw_value is None:
                continue
            value = self._parse_non_negative_int(raw_value)
            if value is None:
                continue
            total += value

        return round(total / 2, 1)


async def get_metrics_reader() -> ApiMetricsReader:
    """Get an ApiMetricsReader using the shared Redis client."""
    redis_client = await get_redis()
    return ApiMetricsReader(redis_client)


__all__ = [
    "ApiMetricsByName",
    "ApiEndpointMetrics",
    "ApiHourlyTrend",
    "ApiMetricsSummary",
    "ApiMetricsReader",
    "get_metrics_reader",
]
