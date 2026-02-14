"""Health check routes."""

import logging

from fastapi import APIRouter, Response, status
from shared.contracts import (
    DependencyHealth,
    DlqHealthSummary,
    HealthMetrics,
    HealthResponse,
    QueueHealthSummary,
    ReadinessMetrics,
)
from sqlalchemy import text

from server.config import get_settings
from server.db.session import get_database
from server.services.dlq import get_dlq_summary
from server.services.events import get_event_processing_stats
from server.services.jobs import get_queue_depth_stats
from server.services.operations import get_alert_delivery_stats
from server.services.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


async def _check_database_readiness() -> DependencyHealth:
    try:
        db = get_database()
    except RuntimeError as exc:
        return DependencyHealth(status="error", detail=str(exc))

    try:
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - defensive guard
        return DependencyHealth(
            status="error",
            detail=f"Database readiness probe failed: {exc}",
        )

    return DependencyHealth(status="ok")


async def _check_redis_readiness(
    redis_url: str | None,
    *,
    required: bool,
) -> DependencyHealth:
    if not redis_url:
        if required:
            return DependencyHealth(
                status="error",
                detail="UPNEXT_REDIS_URL not set",
            )
        return DependencyHealth(
            status="skipped",
            detail="UPNEXT_REDIS_URL not set",
        )

    try:
        redis_client = await get_redis()
    except RuntimeError as exc:
        return DependencyHealth(status="error", detail=str(exc))

    try:
        pong = await redis_client.ping()  # type: ignore[misc]
    except Exception as exc:  # pragma: no cover - defensive guard
        return DependencyHealth(status="error", detail=f"Redis ping failed: {exc}")

    if pong is False:
        return DependencyHealth(status="error", detail="Redis ping returned false")

    return DependencyHealth(status="ok")


async def _get_queue_health() -> QueueHealthSummary:
    """Fetch queue depth stats for health response."""
    try:
        depth = await get_queue_depth_stats()
        return QueueHealthSummary(
            running=depth.running,
            waiting=depth.waiting,
            claimed=depth.claimed,
            backlog=depth.backlog,
            capacity=depth.capacity,
        )
    except Exception:
        return QueueHealthSummary()


async def _get_dlq_health() -> DlqHealthSummary:
    """Fetch DLQ summary for health response."""
    try:
        total_entries, functions_affected = await get_dlq_summary()
        return DlqHealthSummary(
            total_entries=total_entries,
            functions_affected=functions_affected,
        )
    except Exception:
        return DlqHealthSummary()


async def _build_health_response() -> tuple[HealthResponse, bool]:
    settings = get_settings()
    redis_required = bool(
        getattr(settings, "readiness_require_redis", False)
        or getattr(settings, "is_production", False)
    )
    db_readiness = await _check_database_readiness()
    redis_readiness = await _check_redis_readiness(
        settings.redis_url,
        required=redis_required,
    )
    readiness = ReadinessMetrics(
        database=db_readiness,
        redis=redis_readiness,
    )
    if redis_required:
        redis_ready = redis_readiness.status == "ok"
    else:
        redis_ready = redis_readiness.status in {"ok", "skipped"}
    ready = db_readiness.status == "ok" and redis_ready

    # Fetch operational metrics (best-effort, failures don't affect readiness).
    queue_health = await _get_queue_health()
    dlq_health = await _get_dlq_health()
    event_stats = get_event_processing_stats()

    payload = HealthResponse(
        status="ok" if ready else "degraded",
        version=settings.version,
        features=[],
        metrics=HealthMetrics(
            alerts=get_alert_delivery_stats(),
            readiness=readiness,
            queue=queue_health,
            dlq=dlq_health,
            events=event_stats,
        ),
    )
    return payload, ready


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Liveness endpoint with dependency status details.

    This endpoint always returns 200 when the API process is alive.
    See /ready for strict readiness signaling.
    """
    payload, _ = await _build_health_response()
    return payload


@router.get("/ready", response_model=HealthResponse)
async def readiness_check(response: Response) -> HealthResponse:
    """Readiness endpoint for load balancers and traffic gating."""
    payload, ready = await _build_health_response()
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
