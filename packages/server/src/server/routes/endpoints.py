"""API endpoints routes - for tracking HTTP API usage."""

import logging
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from server.services.api_tracking import get_metrics_reader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


# =============================================================================
# Response Models
# =============================================================================


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


class ApiInfo(BaseModel):
    """API-level aggregate info (grouped by API name)."""

    name: str
    endpoint_count: int = 0
    requests_24h: int = 0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    requests_per_min: float = 0.0


class ApisListResponse(BaseModel):
    """APIs list response."""

    apis: list[ApiInfo]
    total: int


class EndpointsListResponse(BaseModel):
    """Endpoints list response (per-endpoint detail)."""

    endpoints: list[ApiEndpoint]
    total: int


class ApiDetailResponse(ApiEndpoint):
    """API endpoint detail response."""

    hourly_stats: list = []
    recent_errors: list = []


class ApiTrendHour(BaseModel):
    """Hourly API response counts by status category."""

    hour: str
    success_2xx: int = 0
    client_4xx: int = 0
    server_5xx: int = 0


class ApiTrendsResponse(BaseModel):
    """API trends response."""

    hourly: list[ApiTrendHour]


# =============================================================================
# Routes
# =============================================================================


@router.get("", response_model=ApisListResponse)
async def list_apis() -> ApisListResponse:
    """List all tracked APIs grouped by name."""
    reader = await get_metrics_reader()
    raw = await reader.get_apis()
    apis = [ApiInfo(**a) for a in raw]
    return ApisListResponse(apis=apis, total=len(apis))


@router.get("/detail", response_model=EndpointsListResponse)
async def list_endpoints() -> EndpointsListResponse:
    """List all tracked API endpoints (per-endpoint detail)."""
    reader = await get_metrics_reader()
    raw = await reader.get_endpoints()
    endpoints = [ApiEndpoint(**ep) for ep in raw]
    return EndpointsListResponse(endpoints=endpoints, total=len(endpoints))


@router.get("/trends", response_model=ApiTrendsResponse)
async def get_api_trends(
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
) -> ApiTrendsResponse:
    """Get hourly API response trends for charts."""
    reader = await get_metrics_reader()
    raw = await reader.get_hourly_trends(hours)
    hourly = [ApiTrendHour(**h) for h in raw]
    return ApiTrendsResponse(hourly=hourly)


@router.get("/{method}/{path:path}", response_model=ApiDetailResponse)
async def get_endpoint(method: str, path: str) -> ApiDetailResponse:
    """Get detailed info for a specific API endpoint."""
    reader = await get_metrics_reader()
    raw = await reader.get_endpoints()
    key = f"{method.upper()}:/{path}"

    for ep in raw:
        if f"{ep['method']}:{ep['path']}" == key:
            return ApiDetailResponse(**ep)

    return ApiDetailResponse(
        method=method.upper(),  # type: ignore
        path=f"/{path}",
    )
