"""API tracking and API dashboard contract payloads."""

from typing import Literal

from pydantic import BaseModel, Field

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class ApiInstance(BaseModel):
    """API instance model (registered via Redis heartbeat)."""

    id: str
    api_name: str
    started_at: str
    last_heartbeat: str
    host: str = "0.0.0.0"
    port: int = 8000
    endpoints: list[str] = Field(default_factory=list)
    hostname: str | None = None


class ApiEndpoint(BaseModel):
    """API endpoint info."""

    method: HttpMethod
    path: str
    requests_24h: int = 0
    requests_per_min: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    error_rate: float = 0.0
    success_rate: float = 100.0
    client_error_rate: float = 0.0
    server_error_rate: float = 0.0
    status_2xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0
    last_request_at: str | None = None


class ApiInfo(BaseModel):
    """API-level aggregate info (grouped by API name)."""

    name: str
    active: bool = False
    instance_count: int = 0
    instances: list[ApiInstance] = Field(default_factory=list)
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


class ApiRequestEvent(BaseModel):
    """Single API request event for live request feed views."""

    id: str
    at: str
    api_name: str
    method: HttpMethod
    path: str
    status: int
    latency_ms: float
    instance_id: str | None = None
    sampled: bool = False


class ApiRequestEventsResponse(BaseModel):
    """Recent API request events response."""

    events: list[ApiRequestEvent]
    total: int


class ApiOverview(BaseModel):
    """Overview metrics for a single API."""

    name: str
    docs_url: str | None = None
    active: bool = False
    instance_count: int = 0
    instances: list[ApiInstance] = Field(default_factory=list)
    endpoint_count: int = 0
    requests_24h: int = 0
    requests_per_min: float = 0.0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    success_rate: float = 100.0
    client_error_rate: float = 0.0
    server_error_rate: float = 0.0


class ApiPageResponse(BaseModel):
    """Payload for API detail dashboard page."""

    api: ApiOverview
    endpoints: list[ApiEndpoint]
    total_endpoints: int


class ApisSnapshotEvent(BaseModel):
    """Realtime snapshot event for the APIs list."""

    type: Literal["apis.snapshot"] = "apis.snapshot"
    at: str
    apis: ApisListResponse


class ApiSnapshotEvent(BaseModel):
    """Realtime snapshot event for a single API detail view."""

    type: Literal["api.snapshot"] = "api.snapshot"
    at: str
    api: ApiPageResponse


class ApiRequestSnapshotEvent(BaseModel):
    """Realtime event for individual API request feed updates."""

    type: Literal["api.request"] = "api.request"
    at: str
    request: ApiRequestEvent


class ApiDetailResponse(ApiEndpoint):
    """API endpoint detail response."""

    hourly_stats: list[dict[str, object]] = Field(default_factory=list)
    recent_errors: list[dict[str, object]] = Field(default_factory=list)


class ApiTrendHour(BaseModel):
    """Hourly API response counts by status category."""

    hour: str
    success_2xx: int = 0
    client_4xx: int = 0
    server_5xx: int = 0


class ApiTrendsResponse(BaseModel):
    """API trends response."""

    hourly: list[ApiTrendHour]


class ApiTrendsSnapshotEvent(BaseModel):
    """Realtime snapshot event for API trends."""

    type: Literal["apis.trends.snapshot"] = "apis.trends.snapshot"
    at: str
    trends: ApiTrendsResponse


__all__ = [
    "HttpMethod",
    "ApiInstance",
    "ApiEndpoint",
    "ApiInfo",
    "ApisListResponse",
    "EndpointsListResponse",
    "ApiRequestEvent",
    "ApiRequestEventsResponse",
    "ApiOverview",
    "ApiPageResponse",
    "ApisSnapshotEvent",
    "ApiSnapshotEvent",
    "ApiRequestSnapshotEvent",
    "ApiDetailResponse",
    "ApiTrendHour",
    "ApiTrendsResponse",
    "ApiTrendsSnapshotEvent",
]
