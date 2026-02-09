"""API endpoints routes - for tracking HTTP API usage."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from shared.events import API_REQUESTS_STREAM
from shared.schemas import (
    ApiDetailResponse,
    ApiEndpoint,
    ApiInfo,
    ApiInstance,
    ApiOverview,
    ApiPageResponse,
    ApiRequestEvent,
    ApiRequestEventsResponse,
    ApiRequestSnapshotEvent,
    ApiSnapshotEvent,
    ApisListResponse,
    ApisSnapshotEvent,
    ApiTrendHour,
    ApiTrendsResponse,
    EndpointsListResponse,
)

from server.config import get_settings
from server.services.api_instances import list_api_instances
from server.services.api_tracking import get_metrics_reader
from server.services import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apis", tags=["apis"])
_snapshot_cache: dict[str, tuple[float, Any]] = {}
_snapshot_cache_lock = asyncio.Lock()


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


def _realtime_interval_seconds() -> float:
    settings = get_settings()
    return max(settings.api_realtime_interval_ms / 1000.0, 0.2)


def _snapshot_cache_ttl_seconds() -> float:
    settings = get_settings()
    return max(settings.api_snapshot_cache_ttl_ms / 1000.0, 0.2)


async def _cached_snapshot(key: str, loader: Any) -> Any:
    now = time.monotonic()
    cached = _snapshot_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    async with _snapshot_cache_lock:
        now = time.monotonic()
        cached = _snapshot_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        value = await loader()
        _snapshot_cache[key] = (now + _snapshot_cache_ttl_seconds(), value)
        return value


def _decode_stream_data(data: dict[Any, Any]) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for key, value in data.items():
        decoded_key = key.decode() if isinstance(key, bytes) else str(key)
        decoded_value = value.decode() if isinstance(value, bytes) else str(value)
        decoded[decoded_key] = decoded_value
    return decoded


def _parse_api_request_event(event_id: str, data: dict[Any, Any]) -> ApiRequestEvent | None:
    decoded = _decode_stream_data(data)
    payload: dict[str, Any] = {}

    raw_json = decoded.get("data")
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                payload.update(parsed)
        except (json.JSONDecodeError, TypeError):
            payload = {}

    if not payload:
        payload = {
            "id": event_id,
            "at": decoded.get("at", datetime.now(UTC).isoformat()),
            "api_name": decoded.get("api_name", ""),
            "method": decoded.get("method", "GET"),
            "path": decoded.get("path", "/"),
            "status": int(decoded.get("status", 0)),
            "latency_ms": float(decoded.get("latency_ms", 0.0)),
            "instance_id": decoded.get("instance_id"),
            "sampled": False,
        }

    payload.setdefault("id", event_id)
    payload.setdefault("at", decoded.get("at", datetime.now(UTC).isoformat()))
    payload.setdefault("api_name", decoded.get("api_name", ""))
    payload.setdefault("method", decoded.get("method", "GET"))
    payload.setdefault("path", decoded.get("path", "/"))
    payload.setdefault("status", int(decoded.get("status", 0)))
    payload.setdefault("latency_ms", 0.0)
    payload.setdefault("sampled", False)

    try:
        payload["status"] = int(payload["status"])
        payload["latency_ms"] = float(payload["latency_ms"])
        payload["method"] = str(payload["method"]).upper()
        if not str(payload.get("api_name", "")).strip():
            return None
        return ApiRequestEvent(**payload)
    except (TypeError, ValueError):
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


@router.get("/events", response_model=ApiRequestEventsResponse)
async def list_api_request_events(
    api_name: str | None = Query(None, description="Optional API name filter"),
    limit: int | None = Query(
        None,
        ge=1,
        le=2000,
        description="Maximum number of recent request events",
    ),
) -> ApiRequestEventsResponse:
    """List recent API request events from the Redis request stream."""
    try:
        redis_client = await get_redis()
    except RuntimeError:
        return ApiRequestEventsResponse(events=[], total=0)

    default_limit = max(get_settings().api_request_events_default_limit, 1)
    effective_limit = min(max(limit or default_limit, 1), 2000)
    read_count = min(max(effective_limit * 4, effective_limit), 5000)

    rows = await redis_client.xrevrange(API_REQUESTS_STREAM, count=read_count)
    events: list[ApiRequestEvent] = []
    for event_id, row in rows:
        parsed = _parse_api_request_event(str(event_id), row)
        if parsed is None:
            continue
        if api_name and parsed.api_name != api_name:
            continue
        events.append(parsed)
        if len(events) >= effective_limit:
            break

    return ApiRequestEventsResponse(events=events, total=len(events))


@router.get("/events/stream")
async def stream_api_request_events(
    request: Request,
    api_name: str | None = Query(None, description="Optional API name filter"),
) -> StreamingResponse:
    """Stream realtime API request events via Server-Sent Events (SSE)."""
    if not get_settings().api_realtime_enabled:
        raise HTTPException(status_code=404, detail="API realtime stream disabled")

    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"
            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {API_REQUESTS_STREAM: last_id},
                    count=100,
                    block=15_000,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                for _stream_name, entries in result:
                    for event_id, row in entries:
                        event_id_str = str(event_id)
                        last_id = event_id_str
                        parsed = _parse_api_request_event(event_id_str, row)
                        if parsed is None:
                            continue
                        if api_name and parsed.api_name != api_name:
                            continue

                        payload = ApiRequestSnapshotEvent(at=parsed.at, request=parsed)
                        yield f"data: {payload.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/stream")
async def stream_apis(request: Request) -> StreamingResponse:
    """Stream realtime API list snapshots via Server-Sent Events (SSE)."""
    if not get_settings().api_realtime_enabled:
        raise HTTPException(status_code=404, detail="API realtime stream disabled")

    interval_seconds = _realtime_interval_seconds()

    async def event_stream():
        yield "event: open\ndata: connected\n\n"
        while True:
            if await request.is_disconnected():
                break

            snapshot = await _cached_snapshot("apis:list", list_apis)
            event = ApisSnapshotEvent(
                at=datetime.now(UTC).isoformat(),
                apis=snapshot,
            )
            yield f"data: {event.model_dump_json()}\n\n"

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/{api_name}/stream")
async def stream_api(api_name: str, request: Request) -> StreamingResponse:
    """Stream realtime snapshot for a single API via SSE."""
    if not get_settings().api_realtime_enabled:
        raise HTTPException(status_code=404, detail="API realtime stream disabled")

    interval_seconds = _realtime_interval_seconds()

    async def event_stream():
        yield "event: open\ndata: connected\n\n"
        while True:
            if await request.is_disconnected():
                break

            snapshot = await _cached_snapshot(f"apis:detail:{api_name}", lambda: get_api(api_name))
            event = ApiSnapshotEvent(
                at=datetime.now(UTC).isoformat(),
                api=snapshot,
            )
            yield f"data: {event.model_dump_json()}\n\n"

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


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
