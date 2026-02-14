"""Queue metrics routes for external monitoring."""

import logging

from fastapi import APIRouter, HTTPException
from shared.contracts import (
    ErrorResponse,
    FunctionQueueMetrics,
    QueueMetricsResponse,
    QueueMetricsTotals,
)

from server.services.dlq import get_dlq_count, list_dlq_functions
from server.services.jobs import get_function_queue_depth_stats, get_queue_depth_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get(
    "/queue",
    response_model=QueueMetricsResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Redis not available."},
    },
)
async def get_queue_metrics() -> QueueMetricsResponse:
    """Per-function queue depth metrics for external monitoring.

    Returns waiting, claimed, and backlog counts per function plus
    DLQ entry counts. Suitable for Prometheus scrapers, Datadog, etc.
    """
    try:
        totals = await get_queue_depth_stats()
        per_function = await get_function_queue_depth_stats()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    # Gather DLQ counts per function.
    dlq_counts: dict[str, int] = {}
    try:
        dlq_functions = await list_dlq_functions()
        for fn in dlq_functions:
            dlq_counts[fn] = await get_dlq_count(fn)
    except Exception:
        pass

    # Merge per-function queue depth + DLQ counts.
    all_functions = sorted(set(per_function.keys()) | set(dlq_counts.keys()))
    function_metrics: list[FunctionQueueMetrics] = []
    total_dlq = 0
    for fn in all_functions:
        depth = per_function.get(fn)
        dlq = dlq_counts.get(fn, 0)
        total_dlq += dlq
        function_metrics.append(
            FunctionQueueMetrics(
                function=fn,
                waiting=depth.waiting if depth else 0,
                claimed=depth.claimed if depth else 0,
                backlog=depth.backlog if depth else 0,
                dlq_entries=dlq,
            )
        )

    return QueueMetricsResponse(
        functions=function_metrics,
        totals=QueueMetricsTotals(
            running=totals.running,
            waiting=totals.waiting,
            claimed=totals.claimed,
            backlog=totals.backlog,
            capacity=totals.capacity,
            dlq_entries=total_dlq,
        ),
    )
