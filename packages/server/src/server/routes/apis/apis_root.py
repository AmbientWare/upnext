"""API endpoints routes - for tracking HTTP API usage."""

import logging

from fastapi import APIRouter, Query
from shared.contracts import (
    ApiDetailResponse,
    ApiEndpoint,
    ApiInfo,
    ApiInstance,
    ApiOverview,
    ApiPageResponse,
    ApisListResponse,
    ApiTrendHour,
    ApiTrendsResponse,
    EndpointsListResponse,
    HttpMethod,
)

from server.routes.apis.apis_utils import build_docs_url
from server.services.apis import (
    ApiEndpointMetrics,
    ApiHourlyTrend,
    ApiMetricsByName,
    get_metrics_reader,
    list_api_instances,
)

logger = logging.getLogger(__name__)

api_root_router = APIRouter(tags=["apis"])
HTTP_METHODS: tuple[HttpMethod, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _coerce_http_method(value: str) -> HttpMethod:
    """Coerce free-form method text into supported HTTP literals."""
    normalized = value.upper()
    if normalized in HTTP_METHODS:
        return normalized
    return "GET"


@api_root_router.get("", response_model=ApisListResponse)
async def list_apis() -> ApisListResponse:
    """List all tracked APIs grouped by name, with active instances."""
    try:
        reader = await get_metrics_reader()
        raw: list[ApiMetricsByName] = await reader.get_apis()
    except RuntimeError:
        raw = []

    # Fetch active instances and group by api_name
    try:
        all_instances = await list_api_instances()
    except Exception:
        all_instances = []

    instances_by_name: dict[str, list[ApiInstance]] = {}
    for inst in all_instances:
        instances_by_name.setdefault(inst.api_name, []).append(inst)

    apis = []
    for api_metrics in raw:
        instances = instances_by_name.get(api_metrics.name, [])
        apis.append(
            ApiInfo(
                name=api_metrics.name,
                endpoint_count=api_metrics.endpoint_count,
                requests_24h=api_metrics.requests_24h,
                avg_latency_ms=api_metrics.avg_latency_ms,
                error_rate=api_metrics.error_rate,
                requests_per_min=api_metrics.requests_per_min,
                active=bool(instances),
                instance_count=len(instances),
                instances=instances,
            )
        )

    # Also include APIs that have active instances but no recent traffic
    tracked_names = {api_metrics.name for api_metrics in raw}
    for api_name, instances in instances_by_name.items():
        if api_name not in tracked_names:
            apis.append(
                ApiInfo(
                    name=api_name,
                    active=True,
                    instance_count=len(instances),
                    instances=instances,
                )
            )

    return ApisListResponse(apis=apis, total=len(apis))


@api_root_router.get("/detail", response_model=EndpointsListResponse)
async def list_endpoints() -> EndpointsListResponse:
    """List all tracked API endpoints (per-endpoint detail)."""
    try:
        reader = await get_metrics_reader()
        raw: list[ApiEndpointMetrics] = await reader.get_endpoints()
    except RuntimeError:
        raw = []
    endpoints = [
        ApiEndpoint(
            method=_coerce_http_method(ep.method),
            path=ep.path,
            requests_24h=ep.requests_24h,
            requests_per_min=ep.requests_per_min,
            avg_latency_ms=ep.avg_latency_ms,
            error_rate=ep.error_rate,
            success_rate=ep.success_rate,
            client_error_rate=ep.client_error_rate,
            server_error_rate=ep.server_error_rate,
            status_2xx=ep.status_2xx,
            status_4xx=ep.status_4xx,
            status_5xx=ep.status_5xx,
        )
        for ep in raw
    ]
    return EndpointsListResponse(endpoints=endpoints, total=len(endpoints))


@api_root_router.get("/trends", response_model=ApiTrendsResponse)
async def get_api_trends(
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
) -> ApiTrendsResponse:
    """Get hourly API response trends for charts."""
    hours_window = hours if isinstance(hours, int) else 24
    try:
        reader = await get_metrics_reader()
        raw: list[ApiHourlyTrend] = await reader.get_hourly_trends(hours_window)
    except RuntimeError:
        raw = []
    hourly = [
        ApiTrendHour(
            hour=item.hour,
            success_2xx=item.success_2xx,
            client_4xx=item.client_4xx,
            server_5xx=item.server_5xx,
        )
        for item in raw
    ]
    return ApiTrendsResponse(hourly=hourly)


@api_root_router.get("/{api_name}", response_model=ApiPageResponse)
async def get_api(api_name: str) -> ApiPageResponse:
    """Get overview + route-level metrics for a single API."""
    try:
        reader = await get_metrics_reader()
        endpoint_rows: list[ApiEndpointMetrics] = await reader.get_endpoints(
            api_name=api_name
        )
    except RuntimeError:
        endpoint_rows = []

    try:
        all_instances = await list_api_instances()
    except Exception:
        all_instances = []

    instances = [inst for inst in all_instances if inst.api_name == api_name]
    endpoints = [
        ApiEndpoint(
            method=_coerce_http_method(row.method),
            path=row.path,
            requests_24h=row.requests_24h,
            requests_per_min=row.requests_per_min,
            avg_latency_ms=row.avg_latency_ms,
            error_rate=row.error_rate,
            success_rate=row.success_rate,
            client_error_rate=row.client_error_rate,
            server_error_rate=row.server_error_rate,
            status_2xx=row.status_2xx,
            status_4xx=row.status_4xx,
            status_5xx=row.status_5xx,
        )
        for row in endpoint_rows
    ]

    requests_24h = sum(ep.requests_24h for ep in endpoints)
    requests_per_min = round(sum(ep.requests_per_min for ep in endpoints), 1)
    status_2xx = sum(ep.status_2xx for ep in endpoints)
    status_4xx = sum(ep.status_4xx for ep in endpoints)
    status_5xx = sum(ep.status_5xx for ep in endpoints)

    weighted_latency = sum(ep.avg_latency_ms * ep.requests_24h for ep in endpoints)
    avg_latency_ms = round(weighted_latency / requests_24h, 2) if requests_24h else 0.0
    error_count = status_4xx + status_5xx
    error_rate = round(error_count / requests_24h * 100, 1) if requests_24h else 0.0
    success_rate = round(status_2xx / requests_24h * 100, 1) if requests_24h else 100.0
    client_error_rate = (
        round(status_4xx / requests_24h * 100, 1) if requests_24h else 0.0
    )
    server_error_rate = (
        round(status_5xx / requests_24h * 100, 1) if requests_24h else 0.0
    )

    overview = ApiOverview(
        name=api_name,
        docs_url=build_docs_url(api_name, instances),
        active=bool(instances),
        instance_count=len(instances),
        instances=instances,
        endpoint_count=len(endpoints),
        requests_24h=requests_24h,
        requests_per_min=requests_per_min,
        avg_latency_ms=avg_latency_ms,
        error_rate=error_rate,
        success_rate=success_rate,
        client_error_rate=client_error_rate,
        server_error_rate=server_error_rate,
    )

    return ApiPageResponse(
        api=overview,
        endpoints=endpoints,
        total_endpoints=len(endpoints),
    )


@api_root_router.get("/{method}/{path:path}", response_model=ApiDetailResponse)
async def get_endpoint(method: str, path: str) -> ApiDetailResponse:
    """Get detailed info for a specific API endpoint."""
    try:
        reader = await get_metrics_reader()
        raw: list[ApiEndpointMetrics] = await reader.get_endpoints()
    except RuntimeError:
        raw = []
    key = f"{method.upper()}:/{path}"

    for ep in raw:
        if f"{ep.method}:{ep.path}" == key:
            return ApiDetailResponse(
                method=_coerce_http_method(ep.method),
                path=ep.path,
                requests_24h=ep.requests_24h,
                requests_per_min=ep.requests_per_min,
                avg_latency_ms=ep.avg_latency_ms,
                error_rate=ep.error_rate,
                success_rate=ep.success_rate,
                client_error_rate=ep.client_error_rate,
                server_error_rate=ep.server_error_rate,
                status_2xx=ep.status_2xx,
                status_4xx=ep.status_4xx,
                status_5xx=ep.status_5xx,
            )

    return ApiDetailResponse(
        method=_coerce_http_method(method),
        path=f"/{path}",
    )
