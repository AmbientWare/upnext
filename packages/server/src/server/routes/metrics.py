"""Queue metrics routes for external monitoring."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from shared.contracts import (
    ErrorResponse,
    FunctionQueueMetrics,
    QueueMetricsResponse,
    QueueMetricsTotals,
)

from server.auth import require_auth_scope
from server.runtime_scope import AuthScope
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
async def get_queue_metrics(
    scope: AuthScope = Depends(require_auth_scope),
) -> QueueMetricsResponse:
    """Per-function queue depth metrics for external monitoring.

    Returns waiting, claimed, and backlog counts per function.
    Suitable for Prometheus scrapers, Datadog, etc.
    """
    try:
        totals = await get_queue_depth_stats(workspace_id=scope.workspace_id)
        per_function = await get_function_queue_depth_stats(
            workspace_id=scope.workspace_id
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    all_functions = sorted(per_function.keys())
    function_metrics: list[FunctionQueueMetrics] = []
    for fn in all_functions:
        depth = per_function.get(fn)
        function_metrics.append(
            FunctionQueueMetrics(
                function=fn,
                waiting=depth.waiting if depth else 0,
                claimed=depth.claimed if depth else 0,
                backlog=depth.backlog if depth else 0,
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
        ),
    )
