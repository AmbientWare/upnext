"""Typed service-layer models for API tracking aggregates."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiMetricsByName:
    """24h aggregate metrics for a single API name."""

    name: str
    endpoint_count: int
    requests_24h: int
    avg_latency_ms: float
    error_rate: float
    requests_per_min: float


@dataclass(frozen=True)
class ApiEndpointMetrics:
    """24h aggregate metrics for a single API endpoint."""

    api_name: str
    method: str
    path: str
    requests_24h: int
    requests_per_min: float
    avg_latency_ms: float
    error_rate: float
    success_rate: float
    client_error_rate: float
    server_error_rate: float
    status_2xx: int
    status_4xx: int
    status_5xx: int


@dataclass(frozen=True)
class ApiHourlyTrend:
    """Hourly status-category counts for trend charts."""

    hour: str
    success_2xx: int
    client_4xx: int
    server_5xx: int


@dataclass(frozen=True)
class ApiMetricsSummary:
    """Top-level API metrics summary used by dashboard stats."""

    requests_24h: int
    avg_latency_ms: float
    error_rate: float


__all__ = [
    "ApiEndpointMetrics",
    "ApiHourlyTrend",
    "ApiMetricsByName",
    "ApiMetricsSummary",
]
