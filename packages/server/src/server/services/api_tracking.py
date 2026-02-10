"""API metrics reader - reads time-bucketed metrics from Redis.

The SDK middleware writes per-endpoint metrics to Redis hash buckets:
- Minute buckets (TTL 10min) for real-time req/min
- Hourly buckets (TTL 30 days) for trends/history

This module reads and aggregates those buckets for the API routes.

Redis key structure (written by upnext.sdk.middleware):
    upnext:api:registry                                    → SET of api names
    upnext:api:{api}:endpoints                             → SET of "METHOD:path"
    upnext:api:{api}:{method}:{path}:m:{YYYY-MM-DDTHH:MM} → HASH (minute)
    upnext:api:{api}:{method}:{path}:h:{YYYY-MM-DDTHH}    → HASH (hourly)
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.api import API_PREFIX

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


async def get_metrics_reader() -> "ApiMetricsReader":
    """Get an ApiMetricsReader using the shared Redis client."""
    redis_client = await get_redis()
    return ApiMetricsReader(redis_client)


class ApiMetricsReader:
    """Reads API metrics from Redis hash buckets."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def get_apis(self) -> list[dict[str, Any]]:
        """Get metrics aggregated by API name (sum of last 24h hourly buckets)."""
        api_names = await self._redis.smembers(f"{API_PREFIX}:registry")
        if not api_names:
            return []

        results = []
        for api_name in api_names:
            endpoints = await self._redis.smembers(f"{API_PREFIX}:{api_name}:endpoints")
            if not endpoints:
                continue

            # Aggregate 24h of hourly buckets across all endpoints
            totals = await self._aggregate_hourly(api_name, endpoints, hours=24)

            if totals["requests"] == 0:
                continue

            results.append(
                {
                    "name": api_name,
                    "endpoint_count": len(endpoints),
                    "requests_24h": totals["requests"],
                    "avg_latency_ms": round(
                        totals["total_latency_ms"] / totals["requests"], 2
                    ),
                    "error_rate": round(totals["errors"] / totals["requests"] * 100, 1),
                    "requests_per_min": await self._get_req_per_min(
                        api_name, endpoints
                    ),
                }
            )

        results.sort(key=lambda a: a["requests_24h"], reverse=True)
        return results

    async def get_endpoints(self, api_name: str | None = None) -> list[dict[str, Any]]:
        """Get per-endpoint metrics. Optionally filter by API name."""
        if api_name:
            api_names = [api_name]
        else:
            api_names = list(await self._redis.smembers(f"{API_PREFIX}:registry") or [])

        results = []
        for name in api_names:
            endpoints = await self._redis.smembers(f"{API_PREFIX}:{name}:endpoints")
            if not endpoints:
                continue

            for ep_key in endpoints:
                parts = ep_key.split(":", 1)
                if len(parts) != 2:
                    continue
                method, path = parts

                totals = await self._aggregate_hourly(name, [ep_key], hours=24)
                if totals["requests"] == 0:
                    continue

                requests = totals["requests"]
                status_2xx = totals["status_2xx"]
                status_4xx = totals["status_4xx"]
                status_5xx = totals["status_5xx"]
                errors = totals["errors"]

                results.append(
                    {
                        "api_name": name,
                        "method": method,
                        "path": path,
                        "requests_24h": requests,
                        "requests_per_min": await self._get_req_per_min(name, [ep_key]),
                        "avg_latency_ms": round(
                            totals["total_latency_ms"] / requests, 2
                        ),
                        "error_rate": round(errors / requests * 100, 1),
                        "success_rate": round(status_2xx / requests * 100, 1),
                        "client_error_rate": round(status_4xx / requests * 100, 1),
                        "server_error_rate": round(status_5xx / requests * 100, 1),
                        "status_2xx": status_2xx,
                        "status_4xx": status_4xx,
                        "status_5xx": status_5xx,
                    }
                )

        results.sort(key=lambda e: e["requests_24h"], reverse=True)
        return results

    async def get_hourly_trends(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get hourly trend data across all APIs for charts."""
        now = datetime.now(UTC)

        # Get all APIs and endpoints
        api_names = await self._redis.smembers(f"{API_PREFIX}:registry") or set()
        all_endpoints: list[tuple[str, str]] = []
        for api_name in api_names:
            endpoints = (
                await self._redis.smembers(f"{API_PREFIX}:{api_name}:endpoints")
                or set()
            )
            for ep in endpoints:
                all_endpoints.append((api_name, ep))

        result = []
        for i in range(hours):
            hour_dt = now - timedelta(hours=hours - i - 1)
            hour_key = hour_dt.strftime("%Y-%m-%dT%H")
            hour_label = hour_dt.strftime("%Y-%m-%dT%H:00:00Z")

            s2xx = 0
            s4xx = 0
            s5xx = 0

            # Read all endpoint buckets for this hour
            if all_endpoints:
                pipe = self._redis.pipeline(transaction=False)
                for api_name, ep_key in all_endpoints:
                    pipe.hgetall(f"{API_PREFIX}:{api_name}:{ep_key}:h:{hour_key}")
                bucket_results = await pipe.execute()

                for data in bucket_results:
                    if data:
                        s2xx += int(data.get("status_2xx", 0))
                        s4xx += int(data.get("status_4xx", 0))
                        s5xx += int(data.get("status_5xx", 0))

            result.append(
                {
                    "hour": hour_label,
                    "success_2xx": s2xx,
                    "client_4xx": s4xx,
                    "server_5xx": s5xx,
                }
            )

        return result

    async def get_summary(self) -> dict[str, Any]:
        """Get summary stats for the dashboard."""
        apis = await self.get_apis()

        total_requests = sum(a["requests_24h"] for a in apis)
        total_latency = sum(a["avg_latency_ms"] * a["requests_24h"] for a in apis)
        total_errors = sum(a["error_rate"] / 100 * a["requests_24h"] for a in apis)

        return {
            "requests_24h": total_requests,
            "avg_latency_ms": round(total_latency / total_requests, 2)
            if total_requests
            else 0,
            "error_rate": round(total_errors / total_requests * 100, 1)
            if total_requests
            else 0,
        }

    async def _aggregate_hourly(
        self, api_name: str, endpoints: set[str] | list[str], hours: int = 24
    ) -> dict[str, Any]:
        """Sum hourly buckets for the given endpoints over N hours."""
        now = datetime.now(UTC)
        hour_keys = [
            (now - timedelta(hours=hours - i - 1)).strftime("%Y-%m-%dT%H")
            for i in range(hours)
        ]

        totals = {
            "requests": 0,
            "errors": 0,
            "total_latency_ms": 0.0,
            "status_2xx": 0,
            "status_4xx": 0,
            "status_5xx": 0,
        }

        # Pipeline: read all endpoint × hour combinations
        pipe = self._redis.pipeline(transaction=False)
        for ep_key in endpoints:
            for h in hour_keys:
                pipe.hgetall(f"{API_PREFIX}:{api_name}:{ep_key}:h:{h}")

        results = await pipe.execute()

        for data in results:
            if data:
                totals["requests"] += int(data.get("requests", 0))
                totals["errors"] += int(data.get("errors", 0))
                totals["total_latency_ms"] += float(data.get("total_latency_ms", 0))
                totals["status_2xx"] += int(data.get("status_2xx", 0))
                totals["status_4xx"] += int(data.get("status_4xx", 0))
                totals["status_5xx"] += int(data.get("status_5xx", 0))

        return totals

    async def _get_req_per_min(
        self, api_name: str, endpoints: set[str] | list[str]
    ) -> float:
        """Get current requests/min from the latest minute bucket."""
        now = datetime.now(UTC)
        # Check last 2 complete minutes (current minute is partial)
        minute_keys = [
            (now - timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M") for i in range(1, 3)
        ]

        pipe = self._redis.pipeline(transaction=False)
        for ep_key in endpoints:
            for m in minute_keys:
                pipe.hget(f"{API_PREFIX}:{api_name}:{ep_key}:m:{m}", "requests")

        results = await pipe.execute()

        total = sum(int(r) for r in results if r)
        # Average over the 2 minutes sampled
        return round(total / 2, 1)
