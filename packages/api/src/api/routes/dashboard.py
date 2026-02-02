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

from api.db.repository import JobRepository
from api.db.session import get_database
from api.services import get_queue_stats, get_worker_stats

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
        queued_count=0,
    )

    recent_runs: list[Run] = []
    recent_failures: list[Run] = []

    # Get active/queued counts from Redis (real-time queue state)
    active_count, queued_count = await get_queue_stats()

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
                queued_count=queued_count,
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

    # API stats - not tracked yet, return defaults
    api_stats = ApiStats(
        requests_24h=0,
        avg_latency_ms=0.0,
        error_rate=0.0,
    )

    return DashboardStats(
        runs=run_stats,
        workers=worker_stats,
        apis=api_stats,
        recent_runs=recent_runs,
        recent_failures=recent_failures,
    )
