"""Job history routes."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from server.db.repository import JobRepository
from server.db.session import get_database
from shared.schemas import JobHistoryResponse, JobListResponse, JobStatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _calculate_duration_ms(
    started_at: datetime | None, completed_at: datetime | None
) -> float | None:
    """Calculate job duration in milliseconds."""
    if started_at and completed_at:
        return (completed_at - started_at).total_seconds() * 1000
    return None


@router.get("/", response_model=JobListResponse)
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
            status=status[0] if status and len(status) == 1 else None,
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
                key=job.key,
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
                state_history=job.state_history,
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


@router.get("/{job_id}", response_model=JobHistoryResponse)
async def get_job(job_id: str) -> JobHistoryResponse:
    """
    Get a specific job by ID.

    Returns job details including full state history.
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
            key=job.key,
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
            state_history=job.state_history,
            duration_ms=_calculate_duration_ms(job.started_at, job.completed_at),
        )


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """Cancel a running or queued job."""
    # TODO: Implement job cancellation via queue
    return {"success": True}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str) -> dict:
    """Retry a failed job."""
    # TODO: Implement job retry via queue
    return {"job_id": job_id}
