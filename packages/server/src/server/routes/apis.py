"""API endpoints routes - for tracking HTTP API usage."""

import logging
from datetime import datetime

from fastapi import APIRouter, Query
from shared.schemas import (
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
)

from server.config import get_settings
from server.services.api_instances import list_api_instances
from server.services.api_tracking import get_metrics_reader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apis", tags=["apis"])


def _normalize_docs_host(host: str) -> str:
    if host in {"0.0.0.0", "::", ""}:
        return "localhost"
    return host


def _build_docs_url(api_name: str, instances: list[ApiInstance]) -> str | None:
    if not instances:
        return None

    try:
        primary = max(
            instances,
            key=lambda item: datetime.fromisoformat(
                item.last_heartbeat.replace("Z", "+00:00")
            ),
        )
    except Exception:
        primary = instances[0]

    settings = get_settings()
    template = settings.api_docs_url_template
    try:
        return template.format(
            api_name=api_name,
            host=_normalize_docs_host(primary.host),
            port=primary.port,
        )
    except Exception:
        logger.exception("Failed to format docs URL for api_name=%s", api_name)
        return None


@router.get("", response_model=ApisListResponse)
async def list_apis() -> ApisListResponse:
    """List all tracked APIs grouped by name, with active instances."""
    try:
        reader = await get_metrics_reader()
        raw = await reader.get_apis()
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
    for a in raw:
        instances = instances_by_name.get(a["name"], [])
        apis.append(
            ApiInfo(
                **a,
                active=bool(instances),
                instance_count=len(instances),
                instances=instances,
            )
        )

    # Also include APIs that have active instances but no recent traffic
    tracked_names = {a["name"] for a in raw}
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


@router.get("/detail", response_model=EndpointsListResponse)
async def list_endpoints() -> EndpointsListResponse:
    """List all tracked API endpoints (per-endpoint detail)."""
    try:
        reader = await get_metrics_reader()
        raw = await reader.get_endpoints()
    except RuntimeError:
        raw = []
    endpoints = [ApiEndpoint(**ep) for ep in raw]
    return EndpointsListResponse(endpoints=endpoints, total=len(endpoints))


@router.get("/trends", response_model=ApiTrendsResponse)
async def get_api_trends(
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
) -> ApiTrendsResponse:
    """Get hourly API response trends for charts."""
    try:
        reader = await get_metrics_reader()
        raw = await reader.get_hourly_trends(hours)
    except RuntimeError:
        raw = []
    hourly = [ApiTrendHour(**h) for h in raw]
    return ApiTrendsResponse(hourly=hourly)


@router.get("/{api_name}", response_model=ApiPageResponse)
async def get_api(api_name: str) -> ApiPageResponse:
    """Get overview + route-level metrics for a single API."""
    try:
        reader = await get_metrics_reader()
        endpoint_rows = await reader.get_endpoints(api_name=api_name)
    except RuntimeError:
        endpoint_rows = []

    try:
        all_instances = await list_api_instances()
    except Exception:
        all_instances = []

    instances = [inst for inst in all_instances if inst.api_name == api_name]
    endpoints = [ApiEndpoint(**ep) for ep in endpoint_rows]

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
        docs_url=_build_docs_url(api_name, instances),
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


@router.get("/{method}/{path:path}", response_model=ApiDetailResponse)
async def get_endpoint(method: str, path: str) -> ApiDetailResponse:
    """Get detailed info for a specific API endpoint."""
    try:
        reader = await get_metrics_reader()
        raw = await reader.get_endpoints()
    except RuntimeError:
        raw = []
    key = f"{method.upper()}:/{path}"

    for ep in raw:
        if f"{ep['method']}:{ep['path']}" == key:
            return ApiDetailResponse(**ep)

    return ApiDetailResponse(
        method=method.upper(),  # type: ignore
        path=f"/{path}",
    )
