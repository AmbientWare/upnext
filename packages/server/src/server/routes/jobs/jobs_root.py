"""Job history routes."""

import json
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from shared.contracts import (
    FunctionType,
    JobCancelResponse,
    JobHistoryResponse,
    JobListResponse,
    JobRetryResponse,
    JobStatsResponse,
    JobTrendHour,
    JobTrendsResponse,
)
from shared.domain import CronSource, EventSource, Job, JobStatus, TaskSource
from shared.keys import status_events_stream_key

from server.auth import require_auth_scope
from server.backends.base import InvalidCursorError, Job as StoredJob, JobHourlyTrendRow
from server.backends.service import BackendService
from server.routes.depends import require_backend
from server.routes.jobs.jobs_utils import (
    job_history_to_response,
)
from server.runtime_scope import AuthScope, RuntimeModes
from server.services.jobs import (
    DuplicateIdempotencyKeyError,
    cancel_job,
    load_job,
    manual_retry,
)
from server.services.redis import get_redis
from server.services.registry import get_function_definitions

router = APIRouter(tags=["jobs"])

VALID_STATUSES = {s.value for s in JobStatus}
STATUS_STREAM_MAXLEN = 50_000


def _history_row_to_runtime_job(row: StoredJob) -> Job:
    source_data = row.source
    source: TaskSource | CronSource | EventSource
    source_type = str(getattr(source_data, "type", "task"))
    if source_type == "cron":
        source = CronSource(
            schedule=getattr(source_data, "schedule"),
            cron_window_at=getattr(source_data, "cron_window_at", None),
            startup_reconciled=bool(getattr(source_data, "startup_reconciled", False)),
            startup_policy=getattr(source_data, "startup_policy", None),
        )
    elif source_type == "event":
        source = EventSource(
            event_pattern=getattr(source_data, "event_pattern"),
            event_handler_name=getattr(source_data, "event_handler_name"),
        )
    else:
        source = TaskSource()

    return Job(
        id=row.id,
        key=getattr(row, "job_key", row.id) or row.id,
        function=row.function,
        function_name=row.function_name,
        kwargs=dict(row.kwargs or {}),
        status=JobStatus(row.status),
        scheduled_at=row.scheduled_at or datetime.now(UTC),
        started_at=row.started_at,
        completed_at=row.completed_at,
        timeout=row.timeout,
        attempts=int(row.attempts or 0),
        max_retries=int(row.max_retries or 0),
        worker_id=row.worker_id,
        parent_id=row.parent_id,
        root_id=row.root_id or row.id,
        progress=float(row.progress or 0.0),
        source=source,
        checkpoint=row.checkpoint,
        checkpoint_at=row.checkpoint_at,
        result=row.result,
        error=row.error,
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    function: str | None = Query(None, description="Filter by function key"),
    status: list[str] | None = Query(None, description="Filter by status"),
    worker_id: str | None = Query(None, description="Filter by worker ID"),
    after: datetime | None = Query(None, description="Filter by created after"),
    before: datetime | None = Query(None, description="Filter by created before"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    cursor: str | None = Query(None, description="Job ID cursor for pagination"),
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> JobListResponse:
    """
    List job history with optional filtering.

    Returns paginated list of jobs using cursor-based pagination.
    Pass `cursor` (a job ID) to fetch the next page of results.
    """
    if status:
        invalid = [s for s in status if s not in VALID_STATUSES]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status values: {invalid}. Valid: {sorted(VALID_STATUSES)}",
            )

    async with backend.session() as tx:
        repo = tx.jobs

        try:
            jobs = await repo.list_jobs(
                function=function,
                status=status,
                worker_id=worker_id,
                start_date=after,
                end_date=before,
                limit=limit + 1,
                cursor=cursor,
                workspace_id=scope.workspace_id,
            )
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        total = await repo.count_jobs(
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=after,
            end_date=before,
            workspace_id=scope.workspace_id,
        )

        has_more = len(jobs) > limit
        if has_more:
            jobs = jobs[:limit]

        job_responses = [job_history_to_response(job) for job in jobs]
        next_cursor = jobs[-1].id if has_more and jobs else None

        return JobListResponse(
            jobs=job_responses,
            total=total,
            has_more=has_more,
            next_cursor=next_cursor,
        )


@router.get("/stats", response_model=JobStatsResponse)
async def get_job_stats(
    function: str | None = Query(None, description="Filter by function key"),
    after: datetime | None = Query(None, description="Filter by start date"),
    before: datetime | None = Query(None, description="Filter by end date"),
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> JobStatsResponse:
    """Get aggregate job statistics."""
    async with backend.session() as tx:
        repo = tx.jobs

        stats = await repo.get_stats(
            function=function,
            start_date=after,
            end_date=before,
            workspace_id=scope.workspace_id,
        )

        return JobStatsResponse(
            total=stats.total,
            success_count=stats.success_count,
            failure_count=stats.failure_count,
            cancelled_count=stats.cancelled_count,
            success_rate=stats.success_rate,
            avg_duration_ms=stats.avg_duration_ms,
        )


@router.get("/trends", response_model=JobTrendsResponse)
async def get_job_trends(
    hours: int = Query(24, ge=1, le=168, description="Number of hours to look back"),
    function: str | None = Query(None, description="Filter by function key"),
    type: FunctionType | None = Query(None, description="Filter by function type"),
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> JobTrendsResponse:
    """
    Get hourly job trends for charts.

    Returns job counts grouped by hour and status for the specified time period.
    """
    allowed_functions: list[str] | None = None
    if type is not None:
        try:
            func_defs = await get_function_definitions(workspace_id=scope.workspace_id)
        except RuntimeError:
            return _empty_trends(hours)

        allowed = [key for key, config in func_defs.items() if config.type == type]
        if function and function not in allowed:
            return _empty_trends(hours)
        if function is None:
            allowed_functions = allowed

    async with backend.session() as tx:
        repo = tx.jobs

        # Calculate time range
        now = datetime.now(UTC)
        start_time = now - timedelta(hours=hours)

        # Get aggregated trends from DB (SQL GROUP BY)
        trend_rows: list[JobHourlyTrendRow] = await repo.get_hourly_trends(
            start_date=start_time,
            end_date=now,
            function=function,
            functions=allowed_functions,
            workspace_id=scope.workspace_id,
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


async def _publish_cancelled_status_event(
    redis_client: Redis,
    job: Job,
    *,
    workspace_id: str,
    reason: str | None = None,
) -> None:
    """Emit job.cancelled so event ingestion and DB history stay in sync."""
    cancelled_at = datetime.now(UTC).isoformat()
    payload = {
        "type": "job.cancelled",
        "workspace_id": workspace_id,
        "job_id": job.id,
        "worker_id": job.worker_id or "server",
        "ts": str(time.time()),
        "data": json.dumps(
            {
                "function": job.function,
                "function_name": job.function_name,
                "parent_id": job.parent_id,
                "root_id": job.root_id or job.id,
                "attempt": job.attempts,
                "reason": reason,
                "cancelled_at": cancelled_at,
            },
            default=str,
        ),
    }
    try:
        await redis_client.xadd(
            status_events_stream_key(workspace_id=workspace_id),
            payload,  # type: ignore[arg-type]
            maxlen=STATUS_STREAM_MAXLEN,
            approximate=True,
        )
    except TypeError:
        await redis_client.xadd(
            status_events_stream_key(workspace_id=workspace_id),
            payload,  # type: ignore[arg-type]
            maxlen=STATUS_STREAM_MAXLEN,
        )
    except Exception:
        # Best effort only; cancel mutation already succeeded.
        return


@router.get("/{job_id}/timeline", response_model=JobListResponse)
async def get_job_timeline(
    job_id: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> JobListResponse:
    """
    Get one job's full execution timeline (root job + descendant jobs).

    Descendants are identified recursively via parent_id.
    """
    async with backend.session() as tx:
        repo = tx.jobs
        jobs = await repo.list_job_subtree(job_id, workspace_id=scope.workspace_id)
        if not jobs:
            raise HTTPException(status_code=404, detail="Job not found")

        return JobListResponse(
            jobs=[job_history_to_response(job) for job in jobs],
            total=len(jobs),
            has_more=False,
        )


@router.get("/{job_id}", response_model=JobHistoryResponse)
async def get_job(
    job_id: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> JobHistoryResponse:
    """Get a specific job by ID."""
    async with backend.session() as tx:
        repo = tx.jobs
        job = await repo.get_by_id(job_id, workspace_id=scope.workspace_id)

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        return job_history_to_response(job)


@router.post("/{job_id}/cancel", response_model=JobCancelResponse)
async def cancel_job_route(
    job_id: str,
    scope: AuthScope = Depends(require_auth_scope),
) -> JobCancelResponse:
    """Cancel a running or queued job."""
    if scope.mode == RuntimeModes.CLOUD_RUNTIME:
        raise HTTPException(
            status_code=501,
            detail="Job cancellation is unavailable in cloud runtime mode",
        )
    try:
        redis_client = await get_redis()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job, job_key = await load_job(redis_client, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status.is_terminal():
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is already in terminal status '{job.status.value}'",
        )

    job.mark_cancelled()
    cancel_result = await cancel_job(
        redis_client,
        job,
        existing_job_key=job_key,
    )
    if not cancel_result.cancelled:
        current, _ = await load_job(redis_client, job_id)
        current_status = current.status.value if current else "terminal"
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job {job_id} cannot be cancelled because it is already "
                f"'{current_status}'."
            ),
        )

    await _publish_cancelled_status_event(
        redis_client,
        job,
        workspace_id=scope.workspace_id,
        reason="Cancelled via API",
    )

    return JobCancelResponse(
        job_id=job.id,
        cancelled=True,
        deleted_stream_entries=cancel_result.deleted_stream_entries,
    )


@router.post("/{job_id}/retry", response_model=JobRetryResponse)
async def retry_job(
    job_id: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> JobRetryResponse:
    """Retry a failed job."""
    if scope.mode == RuntimeModes.CLOUD_RUNTIME:
        raise HTTPException(
            status_code=501,
            detail="Job retry is unavailable in cloud runtime mode",
        )
    try:
        redis_client = await get_redis()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async with backend.session() as tx:
        repo = tx.jobs
        row = await repo.get_by_id(job_id, workspace_id=scope.workspace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    job = _history_row_to_runtime_job(row)

    if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job {job_id} cannot be retried from status '{job.status.value}'. "
                "Only failed/cancelled jobs can be retried."
            ),
        )

    try:
        await manual_retry(redis_client, job)

    except DuplicateIdempotencyKeyError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job {job_id} cannot be retried: idempotency key "
                f"'{exc.idempotency_key}' "
                "is already active."
            ),
        ) from exc

    return JobRetryResponse(job_id=job.id, retried=True)
