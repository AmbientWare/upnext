"""Job history routes."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from shared.models import Job, JobStatus
from shared.queue import QUEUE_KEY_PREFIX
from shared.schemas import (
    FunctionType,
    JobHistoryResponse,
    JobListResponse,
    JobStatsResponse,
    JobTrendHour,
    JobTrendsResponse,
)

from server.db.repository import JobRepository
from server.config import get_settings
from server.db.session import get_database
from server.routes.jobs.jobs_utils import (
    calculate_duration_ms,
)
from server.services.redis import get_redis
from server.services.workers import get_function_definitions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


def _queue_key(*parts: str) -> str:
    return ":".join([QUEUE_KEY_PREFIX, *parts])


def _stream_key(function: str) -> str:
    return _queue_key("fn", function, "stream")


def _scheduled_key(function: str) -> str:
    return _queue_key("fn", function, "scheduled")


def _dedup_key(function: str) -> str:
    return _queue_key("fn", function, "dedup")


def _job_index_key(job_id: str) -> str:
    return _queue_key("job_index", job_id)


def _result_key(job_id: str) -> str:
    return _queue_key("result", job_id)


def _cancel_marker_key(job_id: str) -> str:
    return _queue_key("cancelled", job_id)


def _decode_str(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def _find_job_key_by_id(redis_client: Any, job_id: str) -> str | None:
    index_key = _job_index_key(job_id)
    indexed_job_key = await redis_client.get(index_key)
    if indexed_job_key:
        job_key = _decode_str(indexed_job_key)
        if await redis_client.exists(job_key):
            return job_key
        await redis_client.delete(index_key)

    cursor = 0
    match = f"{QUEUE_KEY_PREFIX}:job:*:{job_id}"
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=match, count=100)
        for key in keys:
            job_key = _decode_str(key)
            if await redis_client.exists(job_key):
                ttl = await redis_client.ttl(job_key)
                if ttl and ttl > 0:
                    await redis_client.setex(index_key, int(ttl), job_key)
                else:
                    await redis_client.set(index_key, job_key)
                return job_key
        if int(cursor) == 0:
            break

    return None


async def _load_job(redis_client: Any, job_id: str) -> tuple[Job | None, str | None]:
    result_data = await redis_client.get(_result_key(job_id))
    if result_data:
        return Job.from_json(_decode_str(result_data)), None

    job_key = await _find_job_key_by_id(redis_client, job_id)
    if job_key is None:
        return None, None

    job_data = await redis_client.get(job_key)
    if not job_data:
        return None, None

    return Job.from_json(_decode_str(job_data)), job_key


async def _delete_stream_entries_for_job(
    redis_client: Any,
    stream_key: str,
    job_id: str,
    *,
    batch_size: int = 500,
    max_scan: int = 50_000,
) -> int:
    start = "-"
    scanned = 0
    deleted = 0

    while scanned < max_scan:
        rows = await redis_client.xrange(
            stream_key, min=start, max="+", count=batch_size
        )
        if not rows:
            break

        delete_ids: list[str] = []
        for msg_id, msg_data in rows:
            scanned += 1
            msg_job_id = msg_data.get(b"job_id") or msg_data.get("job_id")
            if _decode_str(msg_job_id) == job_id:
                delete_ids.append(_decode_str(msg_id))

        if delete_ids:
            deleted += await redis_client.xdel(stream_key, *delete_ids)

        if len(rows) < batch_size:
            break

        start = f"({_decode_str(rows[-1][0])}"

    return deleted


@router.get("", response_model=JobListResponse)
async def list_jobs(
    function: str | None = Query(None, description="Filter by function key"),
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
        total = await repo.count_jobs(
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=after,
            end_date=before,
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
                function_name=job.function_name,
                status=job.status,
                created_at=job.created_at,
                scheduled_at=job.scheduled_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                attempts=job.attempts,
                max_retries=job.max_retries,
                timeout=job.timeout,
                worker_id=job.worker_id,
                parent_id=job.parent_id,
                root_id=job.root_id,
                progress=job.progress,
                kwargs=job.kwargs,
                metadata=job.metadata_,
                result=job.result,
                error=job.error,
                duration_ms=calculate_duration_ms(job.started_at, job.completed_at),
            )
            for job in jobs
        ]

        return JobListResponse(
            jobs=job_responses,
            total=total,
            has_more=has_more,
        )


@router.get("/stats", response_model=JobStatsResponse)
async def get_job_stats(
    function: str | None = Query(None, description="Filter by function key"),
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
    function: str | None = Query(None, description="Filter by function key"),
    type: FunctionType | None = Query(None, description="Filter by function type"),
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

    allowed_functions: list[str] | None = None
    if type is not None:
        try:
            func_defs = await get_function_definitions()
        except RuntimeError:
            return _empty_trends(hours)

        allowed = [
            key
            for key, config in func_defs.items()
            if config.get("type") == type
        ]
        if function and function not in allowed:
            return _empty_trends(hours)
        if function is None:
            allowed_functions = allowed

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
            functions=allowed_functions,
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


@router.get("/{job_id}/timeline", response_model=JobListResponse)
async def get_job_timeline(job_id: str) -> JobListResponse:
    """
    Get one job's full execution timeline (root job + descendant jobs).

    Descendants are identified recursively via parent_id.
    """
    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=404, detail="Job not found")

    async with db.session() as session:
        repo = JobRepository(session)
        jobs = await repo.list_job_subtree(job_id)
        if not jobs:
            raise HTTPException(status_code=404, detail="Job not found")

        return JobListResponse(
            jobs=[
                JobHistoryResponse(
                    id=job.id,
                    function=job.function,
                    function_name=job.function_name,
                    status=job.status,
                    created_at=job.created_at,
                    scheduled_at=job.scheduled_at,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                    attempts=job.attempts,
                    max_retries=job.max_retries,
                    timeout=job.timeout,
                    worker_id=job.worker_id,
                    parent_id=job.parent_id,
                    root_id=job.root_id,
                    progress=job.progress,
                    kwargs=job.kwargs,
                    metadata=job.metadata_,
                    result=job.result,
                    error=job.error,
                    duration_ms=calculate_duration_ms(
                        job.started_at, job.completed_at
                    ),
                )
                for job in jobs
            ],
            total=len(jobs),
            has_more=False,
        )


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
            function_name=job.function_name,
            status=job.status,
            created_at=job.created_at,
            scheduled_at=job.scheduled_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            attempts=job.attempts,
            max_retries=job.max_retries,
            timeout=job.timeout,
            worker_id=job.worker_id,
            parent_id=job.parent_id,
            root_id=job.root_id,
            progress=job.progress,
            kwargs=job.kwargs,
            metadata=job.metadata_,
            result=job.result,
            error=job.error,
            duration_ms=calculate_duration_ms(job.started_at, job.completed_at),
        )


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """Cancel a running or queued job."""
    settings = get_settings()

    try:
        redis_client = await get_redis()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job, job_key = await _load_job(redis_client, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status.is_terminal():
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is already in terminal status '{job.status.value}'",
        )

    job.mark_cancelled()

    stream_key = _stream_key(job.function)
    scheduled_key = _scheduled_key(job.function)
    dedup_key = _dedup_key(job.function)
    index_key = _job_index_key(job.id)
    result_key = _result_key(job.id)
    cancel_marker_key = _cancel_marker_key(job.id)

    await redis_client.setex(
        cancel_marker_key,
        max(1, settings.queue_job_ttl_seconds),
        "1",
    )
    await redis_client.zrem(scheduled_key, job.id)
    deleted_from_stream = await _delete_stream_entries_for_job(
        redis_client, stream_key, job.id
    )

    await redis_client.setex(
        result_key,
        max(1, settings.queue_result_ttl_seconds),
        job.to_json(),
    )
    if job_key:
        await redis_client.delete(job_key)
    await redis_client.delete(index_key)
    if job.key:
        await redis_client.srem(dedup_key, job.key)

    await redis_client.publish(f"upnext:job:{job.id}", JobStatus.CANCELLED.value)

    return {
        "job_id": job.id,
        "cancelled": True,
        "deleted_stream_entries": deleted_from_stream,
    }


@router.post("/{job_id}/retry")
async def retry_job(job_id: str) -> dict:
    """Retry a failed job."""
    settings = get_settings()

    try:
        redis_client = await get_redis()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job, _ = await _load_job(redis_client, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job {job_id} cannot be retried from status '{job.status.value}'. "
                "Only failed/cancelled jobs can be retried."
            ),
        )

    job.mark_queued("Manual retry requested")
    job.started_at = None
    job.completed_at = None
    job.worker_id = None
    job.error = None
    job.error_traceback = None
    job.result = None
    job.progress = 0.0
    if job.metadata is None:
        job.metadata = {}
    job.metadata.pop("_stream_key", None)
    job.metadata.pop("_stream_msg_id", None)

    job_key = _queue_key("job", job.function, job.id)
    index_key = _job_index_key(job.id)
    stream_key = _stream_key(job.function)
    scheduled_key = _scheduled_key(job.function)

    await redis_client.setex(
        job_key,
        max(1, settings.queue_job_ttl_seconds),
        job.to_json(),
    )
    await redis_client.setex(
        index_key,
        max(1, settings.queue_job_ttl_seconds),
        job_key,
    )
    await redis_client.delete(_result_key(job.id))
    await redis_client.delete(_cancel_marker_key(job.id))
    await redis_client.zrem(scheduled_key, job.id)

    payload = {"job_id": job.id, "function": job.function, "data": job.to_json()}
    stream_maxlen = max(0, settings.queue_stream_maxlen)
    if stream_maxlen > 0:
        try:
            await redis_client.xadd(
                stream_key,
                payload,
                maxlen=stream_maxlen,
                approximate=True,
            )
        except TypeError:
            await redis_client.xadd(stream_key, payload, maxlen=stream_maxlen)
    else:
        await redis_client.xadd(stream_key, payload)

    return {"job_id": job.id, "retried": True}
