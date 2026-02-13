"""Dashboard routes - aggregate stats for dashboard home."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from shared.contracts import (
    ApiStats,
    DashboardStats,
    OldestQueuedJob,
    QueueStats,
    Run,
    RunStats,
    StuckActiveJob,
    TopFailingFunction,
)

from server.config import get_settings
from server.db.repositories import JobRepository
from server.db.session import get_database
from server.services.apis import ApiMetricsSummary, get_metrics_reader
from server.services.jobs import get_oldest_queued_jobs, get_queue_depth_stats
from server.services.registry import get_function_definitions, get_worker_stats
from server.shared_utils import as_utc_aware

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats() -> DashboardStats:
    """
    Get aggregated dashboard statistics.

    Combines run stats, worker stats, API stats, and recent activity.
    """
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    # Default empty stats
    run_stats = RunStats(
        total_24h=0,
        success_rate=100.0,
    )
    queue_depth = await get_queue_depth_stats()
    queue_stats = QueueStats(
        running=queue_depth.running,
        waiting=queue_depth.waiting,
        claimed=queue_depth.claimed,
        capacity=queue_depth.capacity,
        total=queue_depth.total,
    )

    recent_runs: list[Run] = []
    recent_failures: list[Run] = []
    top_failing_functions: list[TopFailingFunction] = []
    oldest_queued_jobs: list[OldestQueuedJob] = []
    stuck_active_jobs: list[StuckActiveJob] = []
    settings = get_settings()

    function_name_map: dict[str, str] = {}
    try:
        function_defs = await get_function_definitions()
        function_name_map = {key: cfg.name for key, cfg in function_defs.items()}
    except RuntimeError:
        function_name_map = {}

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            # Get stats for last 24 hours
            stats = await repo.get_stats(start_date=day_ago)

            run_stats = RunStats(
                total_24h=stats.total,
                success_rate=stats.success_rate,
            )

            function_stats = await repo.get_function_job_stats(start_date=day_ago)
            top_candidates: list[TopFailingFunction] = []
            for function_key, item in function_stats.items():
                if item.runs < 1 or item.failures < 1:
                    continue
                failure_rate = round((item.failures / item.runs) * 100, 2)
                top_candidates.append(
                    TopFailingFunction(
                        key=function_key,
                        name=function_name_map.get(function_key, function_key),
                        runs_24h=item.runs,
                        failures_24h=item.failures,
                        failure_rate=failure_rate,
                        last_run_at=item.last_run_at,
                    )
                )
            top_candidates.sort(
                key=lambda row: (
                    -row.failures_24h,
                    -row.failure_rate,
                    -row.runs_24h,
                    row.name,
                )
            )
            top_failing_functions = top_candidates[
                : max(0, settings.dashboard_top_failing_limit)
            ]

            stuck_rows = await repo.list_stuck_active_jobs(
                started_before=now
                - timedelta(seconds=max(0, settings.dashboard_stuck_active_seconds)),
                limit=max(0, settings.dashboard_stuck_active_limit),
            )
            for stuck in stuck_rows:
                started_at = as_utc_aware(stuck.started_at)
                if started_at is None:
                    continue
                age_seconds = max(0.0, (now - started_at).total_seconds())
                stuck_active_jobs.append(
                    StuckActiveJob(
                        id=stuck.id,
                        function=stuck.function,
                        function_name=stuck.function_name,
                        worker_id=stuck.worker_id,
                        started_at=started_at.isoformat(),
                        age_seconds=round(age_seconds, 2),
                    )
                )

            # Get recent runs (last 10)
            recent_jobs = await repo.list_jobs(limit=10)
            for job in recent_jobs:
                duration_ms = None
                if job.started_at and job.completed_at:
                    duration_ms = (
                        job.completed_at - job.started_at
                    ).total_seconds() * 1000

                recent_runs.append(
                    Run(
                        id=job.id,
                        function=job.function,
                        function_name=job.function_name,
                        status=job.status,
                        started_at=job.started_at.isoformat()
                        if job.started_at
                        else None,
                        completed_at=job.completed_at.isoformat()
                        if job.completed_at
                        else None,
                        duration_ms=duration_ms,
                        error=job.error,
                        worker_id=job.worker_id,
                        attempts=job.attempts or 1,
                        progress=job.progress or 0.0,
                    )
                )

            # Get recent failures (last 10)
            failed_jobs = await repo.list_jobs(status="failed", limit=10)
            for job in failed_jobs:
                duration_ms = None
                if job.started_at and job.completed_at:
                    duration_ms = (
                        job.completed_at - job.started_at
                    ).total_seconds() * 1000

                recent_failures.append(
                    Run(
                        id=job.id,
                        function=job.function,
                        function_name=job.function_name,
                        status=job.status,
                        started_at=job.started_at.isoformat()
                        if job.started_at
                        else None,
                        completed_at=job.completed_at.isoformat()
                        if job.completed_at
                        else None,
                        duration_ms=duration_ms,
                        error=job.error,
                        worker_id=job.worker_id,
                        attempts=job.attempts or 1,
                        progress=job.progress or 0.0,
                    )
                )

    except RuntimeError:
        # Database not available
        logger.debug("Database not available for dashboard stats")

    oldest_queued = await get_oldest_queued_jobs(
        limit=max(0, settings.dashboard_oldest_queued_limit),
    )
    oldest_queued_jobs = [
        OldestQueuedJob(
            id=item.id,
            function=item.function,
            function_name=item.function_name,
            queued_at=item.queued_at.isoformat(),
            age_seconds=round(item.age_seconds, 2),
            source=item.source,
        )
        for item in oldest_queued
    ]

    # Worker stats from Redis
    worker_stats = await get_worker_stats()

    # API stats from Redis hash buckets
    try:
        reader = await get_metrics_reader()
        api_summary = await reader.get_summary()
    except RuntimeError:
        api_summary = ApiMetricsSummary(
            requests_24h=0,
            avg_latency_ms=0.0,
            error_rate=0.0,
        )
    api_stats = ApiStats(
        requests_24h=api_summary.requests_24h,
        avg_latency_ms=api_summary.avg_latency_ms,
        error_rate=api_summary.error_rate,
    )

    return DashboardStats(
        runs=run_stats,
        queue=queue_stats,
        workers=worker_stats,
        apis=api_stats,
        recent_runs=recent_runs,
        recent_failures=recent_failures,
        top_failing_functions=top_failing_functions,
        oldest_queued_jobs=oldest_queued_jobs,
        stuck_active_jobs=stuck_active_jobs,
    )
