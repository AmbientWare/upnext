"""API endpoints routes - for tracking HTTP API usage."""

import logging

from fastapi import APIRouter, Query
from shared.schemas import (
    ApiDetailResponse,
    ApiEndpoint,
    ApiInfo,
    ApiInstance,
    ApisListResponse,
    ApiTrendHour,
    ApiTrendsResponse,
    EndpointsListResponse,
)

from server.services.api_instances import list_api_instances
from server.services.api_tracking import get_metrics_reader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apis", tags=["apis"])


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
