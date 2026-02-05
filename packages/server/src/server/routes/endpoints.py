"""API endpoints routes - for tracking HTTP API usage."""

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class ApiEndpoint(BaseModel):
    """API endpoint info."""

    method: HttpMethod
    path: str
    requests_24h: int = 0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    error_rate: float = 0.0
    last_request_at: str | None = None


class ApisListResponse(BaseModel):
    """APIs list response."""

    endpoints: list[ApiEndpoint]
    total: int


class HourlyStat(BaseModel):
    """Hourly stat for endpoint detail."""

    hour: str
    requests: int
    errors: int
    avg_latency_ms: float


class RecentError(BaseModel):
    """Recent error for endpoint detail."""

    status_code: int
    message: str
    timestamp: str


class ApiDetailResponse(ApiEndpoint):
    """API endpoint detail response."""

    hourly_stats: list[HourlyStat] = []
    recent_errors: list[RecentError] = []


# In-memory endpoint tracking (would be in Redis/DB in production)
_tracked_endpoints: dict[str, dict] = {}


def track_request(
    method: str,
    path: str,
    latency_ms: float,
    status_code: int,
    error_message: str | None = None,
) -> None:
    """Track an API request (called by middleware)."""
    key = f"{method}:{path}"

    if key not in _tracked_endpoints:
        _tracked_endpoints[key] = {
            "method": method,
            "path": path,
            "requests": 0,
            "total_latency_ms": 0,
            "errors": 0,
            "last_request_at": None,
        }

    endpoint = _tracked_endpoints[key]
    endpoint["requests"] += 1
    endpoint["total_latency_ms"] += latency_ms
    endpoint["last_request_at"] = None  # Would set to current time

    if status_code >= 400:
        endpoint["errors"] += 1


@router.get("/", response_model=ApisListResponse)
async def list_endpoints() -> ApisListResponse:
    """
    List all tracked API endpoints.

    Note: API tracking is not yet implemented. Returns empty list.
    """
    endpoints: list[ApiEndpoint] = []

    for key, data in _tracked_endpoints.items():
        requests = data["requests"]
        avg_latency = (data["total_latency_ms"] / requests) if requests > 0 else 0
        error_rate = (data["errors"] / requests * 100) if requests > 0 else 0

        endpoints.append(
            ApiEndpoint(
                method=data["method"],
                path=data["path"],
                requests_24h=requests,
                avg_latency_ms=round(avg_latency, 2),
                p50_latency_ms=round(avg_latency, 2),  # Simplified
                p95_latency_ms=round(avg_latency * 1.5, 2),  # Simplified
                p99_latency_ms=round(avg_latency * 2, 2),  # Simplified
                error_rate=round(error_rate, 1),
                last_request_at=data["last_request_at"],
            )
        )

    # Sort by requests (most active first)
    endpoints.sort(key=lambda e: e.requests_24h, reverse=True)

    return ApisListResponse(endpoints=endpoints, total=len(endpoints))


@router.get("/{method}/{path:path}", response_model=ApiDetailResponse)
async def get_endpoint(method: str, path: str) -> ApiDetailResponse:
    """
    Get detailed info for a specific API endpoint.

    Note: API tracking is not yet implemented. Returns empty data.
    """
    key = f"{method}:/{path}"
    data = _tracked_endpoints.get(key, {})

    requests = data.get("requests", 0)
    avg_latency = (data.get("total_latency_ms", 0) / requests) if requests > 0 else 0
    error_rate = (data.get("errors", 0) / requests * 100) if requests > 0 else 0

    return ApiDetailResponse(
        method=method.upper(),  # type: ignore
        path=f"/{path}",
        requests_24h=requests,
        avg_latency_ms=round(avg_latency, 2),
        p50_latency_ms=round(avg_latency, 2),
        p95_latency_ms=round(avg_latency * 1.5, 2),
        p99_latency_ms=round(avg_latency * 2, 2),
        error_rate=round(error_rate, 1),
        last_request_at=data.get("last_request_at"),
        hourly_stats=[],
        recent_errors=[],
    )
