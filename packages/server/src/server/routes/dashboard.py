"""Dashboard routes - aggregate stats for dashboard home."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from shared.schemas import (
    ApiStats,
    DashboardStats,
    Run,
    RunStats,
)

from server.db.repository import JobRepository
from server.db.session import get_database
from server.services import get_active_job_count, get_worker_stats
from server.services.api_tracking import get_metrics_reader

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
        active_count=0,
    )

    recent_runs: list[Run] = []
    recent_failures: list[Run] = []

    # Get active job count from Redis (real-time from worker heartbeats)
    active_count = await get_active_job_count()

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            # Get stats for last 24 hours
            stats = await repo.get_stats(start_date=day_ago)

            run_stats = RunStats(
                total_24h=stats["total"],
                success_rate=stats["success_rate"],
                active_count=active_count,
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

    # Worker stats from Redis
    worker_stats = await get_worker_stats()

    # API stats from Redis hash buckets
    try:
        reader = await get_metrics_reader()
        api_summary = await reader.get_summary()
    except RuntimeError:
        api_summary = {"requests_24h": 0, "avg_latency_ms": 0, "error_rate": 0}
    api_stats = ApiStats(
        requests_24h=api_summary["requests_24h"],
        avg_latency_ms=api_summary["avg_latency_ms"],
        error_rate=api_summary["error_rate"],
    )

    return DashboardStats(
        runs=run_stats,
        workers=worker_stats,
        apis=api_stats,
        recent_runs=recent_runs,
        recent_failures=recent_failures,
    )
