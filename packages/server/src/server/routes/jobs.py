"""Job history routes."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from shared.schemas import (
    JobHistoryResponse,
    JobListResponse,
    JobStatsResponse,
    JobTrendHour,
    JobTrendsResponse,
)

from server.db.repository import JobRepository
from server.db.session import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _calculate_duration_ms(
    started_at: datetime | None, completed_at: datetime | None
) -> float | None:
    """Calculate job duration in milliseconds."""
    if started_at and completed_at:
        return (completed_at - started_at).total_seconds() * 1000
    return None


@router.get("", response_model=JobListResponse)
async def list_jobs(
    function: str | None = Query(None, description="Filter by function name"),
    status: list[str] | None = Query(None, description="Filter by status"),
    worker_id: str | None = Query(None, description="Filter by worker ID"),
    after: datetime | None = Query(None, description="Filter by created after"),
    before: datetime | None = Query(None, description="Filter by created before"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> JobListResponse:
    """
    List job history with optional filtering.

    Returns paginated list of completed jobs.
    """
    try:
        db = get_database()
    except RuntimeError:
        return JobListResponse(jobs=[], total=0, has_more=False)

    async with db.session() as session:
        repo = JobRepository(session)

        # Get one more than limit to check if there are more
        jobs = await repo.list_jobs(
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=after,
            end_date=before,
            limit=limit + 1,
            offset=offset,
        )

        # Check if there are more results
        has_more = len(jobs) > limit
        if has_more:
            jobs = jobs[:limit]

        # Convert to response models with duration_ms
        job_responses = [
            JobHistoryResponse(
                id=job.id,
                function=job.function,
                status=job.status,
                created_at=job.created_at,
                scheduled_at=job.scheduled_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                attempts=job.attempts,
                max_retries=job.max_retries,
                timeout=job.timeout,
                worker_id=job.worker_id,
                progress=job.progress,
                kwargs=job.kwargs,
                metadata=job.metadata_,
                result=job.result,
                error=job.error,
                duration_ms=_calculate_duration_ms(job.started_at, job.completed_at),
            )
            for job in jobs
        ]

        return JobListResponse(
            jobs=job_responses,
            total=len(job_responses) + offset,  # Approximate total
            has_more=has_more,
        )


@router.get("/stats", response_model=JobStatsResponse)
async def get_job_stats(
    function: str | None = Query(None, description="Filter by function name"),
    after: datetime | None = Query(None, description="Filter by start date"),
    before: datetime | None = Query(None, description="Filter by end date"),
) -> JobStatsResponse:
    """
    Get aggregate job statistics.

    Returns counts and success rates for jobs.
    """
    try:
        db = get_database()
    except RuntimeError:
        return JobStatsResponse(
            total=0,
            success_count=0,
            failure_count=0,
            cancelled_count=0,
            success_rate=100.0,
            avg_duration_ms=None,
        )

    async with db.session() as session:
        repo = JobRepository(session)

        stats = await repo.get_stats(
            function=function,
            start_date=after,
            end_date=before,
        )

        return JobStatsResponse(
            total=stats["total"],
            success_count=stats["success_count"],
            failure_count=stats["failure_count"],
            cancelled_count=stats["cancelled_count"],
            success_rate=stats["success_rate"],
            avg_duration_ms=None,  # TODO: Calculate from jobs
        )


@router.get("/trends", response_model=JobTrendsResponse)
async def get_job_trends(
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
    function: str | None = Query(None, description="Filter by function name"),
    type: str | None = Query(None, description="Filter by function type"),
) -> JobTrendsResponse:
    """
    Get hourly job trends for charts.

    Returns job counts grouped by hour and status for the specified time period.
    """
    try:
        db = get_database()
    except RuntimeError:
        # Return empty hours when no database
        return _empty_trends(hours)

    async with db.session() as session:
        repo = JobRepository(session)

        # Calculate time range
        now = datetime.now(UTC)
        start_time = now - timedelta(hours=hours)

        # Get aggregated trends from DB (SQL GROUP BY)
        trend_rows = await repo.get_hourly_trends(
            start_date=start_time,
            end_date=now,
            function=function,
        )

        # Initialize all hours
        hourly_counts: dict[str, dict[str, int]] = {}
        for i in range(hours):
            hour_start = now - timedelta(hours=hours - i - 1)
            hour_key = hour_start.replace(minute=0, second=0, microsecond=0).strftime(
                "%Y-%m-%dT%H:00:00Z"
            )
            hourly_counts[hour_key] = {
                "complete": 0,
                "failed": 0,
                "retrying": 0,
                "active": 0,
            }

        # Fill in counts from aggregated DB results
        for row in trend_rows:
            hour_dt = datetime(int(row.yr), int(row.mo), int(row.dy), int(row.hr))
            hour_key = hour_dt.strftime("%Y-%m-%dT%H:00:00Z")
            if hour_key in hourly_counts:
                status = row.status.lower()
                if status in hourly_counts[hour_key]:
                    hourly_counts[hour_key][status] = row.cnt

        # Convert to response
        hourly = [
            JobTrendHour(hour=hour, **counts)
            for hour, counts in sorted(hourly_counts.items())
        ]

        return JobTrendsResponse(hourly=hourly)


def _empty_trends(hours: int) -> JobTrendsResponse:
    """Return empty trends data for the given hours."""
    now = datetime.now(UTC)
    hourly = []

    for i in range(hours):
        hour_start = now - timedelta(hours=hours - i - 1)
        hour_key = hour_start.replace(minute=0, second=0, microsecond=0).strftime(
            "%Y-%m-%dT%H:00:00Z"
        )
        hourly.append(JobTrendHour(hour=hour_key))

    return JobTrendsResponse(hourly=hourly)


@router.get("/{job_id}", response_model=JobHistoryResponse)
async def get_job(job_id: str) -> JobHistoryResponse:
    """
    Get a specific job by ID.

    Returns job details.
    """
    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=404, detail="Job not found")

    async with db.session() as session:
        repo = JobRepository(session)
        job = await repo.get_by_id(job_id)

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return JobHistoryResponse(
            id=job.id,
            function=job.function,
            status=job.status,
            created_at=job.created_at,
            scheduled_at=job.scheduled_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            attempts=job.attempts,
            max_retries=job.max_retries,
            timeout=job.timeout,
            worker_id=job.worker_id,
            progress=job.progress,
            kwargs=job.kwargs,
            metadata=job.metadata_,
            result=job.result,
            error=job.error,
            duration_ms=_calculate_duration_ms(job.started_at, job.completed_at),
        )


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """Cancel a running or queued job."""
    raise HTTPException(
        status_code=501,
        detail=f"Job cancellation is not implemented yet for job {job_id}",
    )


@router.post("/{job_id}/retry")
async def retry_job(job_id: str) -> dict:
    """Retry a failed job."""
    raise HTTPException(
        status_code=501,
        detail=f"Job retry is not implemented yet for job {job_id}",
    )
