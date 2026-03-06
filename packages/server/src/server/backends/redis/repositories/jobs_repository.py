"""Redis-backed job repository."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

from pydantic import ValidationError
from redis.asyncio import Redis
from shared.keys import DEFAULT_DEPLOYMENT_ID

from server.backends.base.exceptions import InvalidCursorError
from server.backends.base.models import Job
from server.backends.base.repositories import BaseJobRepository
from server.backends.base.repository_models import (
    FunctionJobStats,
    FunctionWaitStats,
    JobHourlyTrendRow,
    JobRecordCreate,
    JobStatsSummary,
)
from server.backends.redis.repositories._utils import (
    decode_text,
    dumps,
    loads,
    utcnow,
)
from server.backends.redis.repositories.typing import AsyncRedisClient

_JOBS_SET = "upnext:persist:jobs:ids"


def _job_key(job_id: str) -> str:
    return f"upnext:persist:jobs:{job_id}"


def _encode_job(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "deployment_id": job.deployment_id,
        "job_key": job.job_key,
        "function": job.function,
        "function_name": job.function_name,
        "job_type": job.job_type,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "queue_wait_ms": job.queue_wait_ms,
        "attempts": job.attempts,
        "max_retries": job.max_retries,
        "timeout": job.timeout,
        "worker_id": job.worker_id,
        "parent_id": job.parent_id,
        "root_id": job.root_id,
        "progress": job.progress,
        "kwargs": job.kwargs,
        "schedule": job.schedule,
        "cron_window_at": job.cron_window_at,
        "startup_reconciled": job.startup_reconciled,
        "startup_policy": job.startup_policy,
        "checkpoint": job.checkpoint,
        "checkpoint_at": job.checkpoint_at,
        "event_pattern": job.event_pattern,
        "event_handler_name": job.event_handler_name,
        "result": job.result,
        "error": job.error,
    }


def _decode_job(payload: dict[str, object]) -> Job | None:
    normalized = dict(payload)
    if not normalized.get("root_id"):
        normalized["root_id"] = normalized.get("id")
    if not isinstance(normalized.get("kwargs"), dict):
        normalized["kwargs"] = {}
    try:
        return BaseJobRepository._to_model(normalized)
    except ValidationError:
        return None


class RedisJobRepository(BaseJobRepository):
    def __init__(self, redis: Redis) -> None:
        self._redis: AsyncRedisClient = cast(AsyncRedisClient, redis)

    async def _read_job(self, job_id: str) -> Job | None:
        payload = loads(await self._redis.get(_job_key(job_id)))
        return _decode_job(payload) if payload else None

    async def _write_job(self, job: Job) -> None:
        now = utcnow()
        if job.created_at is None:
            job.created_at = now
        job.updated_at = now
        await self._redis.set(_job_key(job.id), dumps(_encode_job(job)))
        await self._redis.sadd(_JOBS_SET, job.id)

    async def _all_jobs(self) -> list[Job]:
        ids = await self._redis.smembers(_JOBS_SET)
        out: list[Job] = []
        for raw_id in ids:
            job = await self._read_job(decode_text(raw_id))
            if job is not None:
                out.append(job)
        return out

    async def record_job(self, data: JobRecordCreate | Mapping[str, object]) -> Job:
        payload = (
            data
            if isinstance(data, JobRecordCreate)
            else JobRecordCreate.model_validate(data)
        )
        now = utcnow()
        job = Job(
            id=payload.id,
            deployment_id=payload.deployment_id,
            job_key=payload.job_key or payload.id,
            function=payload.function,
            function_name=payload.function_name or payload.function,
            job_type=payload.job_type.value
            if hasattr(payload.job_type, "value")
            else str(payload.job_type),
            status=payload.status,
            created_at=payload.created_at or now,
            scheduled_at=payload.scheduled_at,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            attempts=payload.attempts,
            max_retries=payload.max_retries,
            timeout=payload.timeout,
            worker_id=payload.worker_id,
            parent_id=payload.parent_id,
            root_id=payload.root_id or payload.id,
            progress=payload.progress,
            kwargs=dict(payload.kwargs or {}),
            schedule=payload.schedule,
            cron_window_at=payload.cron_window_at,
            startup_reconciled=payload.startup_reconciled,
            startup_policy=payload.startup_policy,
            checkpoint=payload.checkpoint,
            checkpoint_at=payload.checkpoint_at,
            event_pattern=payload.event_pattern,
            event_handler_name=payload.event_handler_name,
            queue_wait_ms=payload.queue_wait_ms,
            result=payload.result,
            error=payload.error,
        )
        await self._write_job(job)
        return job

    async def get_by_id(
        self,
        id: str,
        *,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> Job | None:
        job = await self._read_job(id)
        if job is None or job.deployment_id != deployment_id:
            return None
        return job

    async def list_job_subtree(
        self, id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[Job]:
        root = await self.get_by_id(id, deployment_id=deployment_id)
        if root is None:
            return []
        all_jobs = [
            job for job in await self._all_jobs() if job.deployment_id == deployment_id
        ]
        by_parent: dict[str, list[Job]] = defaultdict(list)
        for job in all_jobs:
            if job.parent_id:
                by_parent[job.parent_id].append(job)
        out: list[Job] = []
        seen: set[str] = set()
        frontier: list[str] = [root.id]
        by_id = {job.id: job for job in all_jobs}
        by_id[root.id] = root
        while frontier:
            current = frontier.pop(0)
            if current in seen:
                continue
            seen.add(current)
            node = by_id.get(current)
            if node is not None:
                out.append(node)
            for child in by_parent.get(current, []):
                if child.id not in seen:
                    frontier.append(child.id)
        out.sort(
            key=lambda job: (
                job.started_at
                or job.created_at
                or job.scheduled_at
                or job.completed_at
                or datetime.min.replace(tzinfo=UTC),
                job.id,
            )
        )
        return out

    async def list_jobs(
        self,
        *,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[Job]:
        jobs = [
            job for job in await self._all_jobs() if job.deployment_id == deployment_id
        ]
        if function:
            jobs = [job for job in jobs if job.function == function]
        if isinstance(status, str) and status:
            jobs = [job for job in jobs if job.status == status]
        elif isinstance(status, list) and status:
            allowed = set(status)
            jobs = [job for job in jobs if job.status in allowed]
        if worker_id:
            jobs = [job for job in jobs if job.worker_id == worker_id]
        if start_date:
            jobs = [
                job for job in jobs if job.created_at and job.created_at >= start_date
            ]
        if end_date:
            jobs = [
                job for job in jobs if job.created_at and job.created_at <= end_date
            ]

        jobs.sort(
            key=lambda item: (
                item.created_at or datetime.min.replace(tzinfo=UTC),
                item.id,
            ),
            reverse=True,
        )

        if cursor:
            cursor_job = await self.get_by_id(cursor, deployment_id=deployment_id)
            if cursor_job is None:
                raise InvalidCursorError(
                    f"Cursor job '{cursor}' not found. "
                    "The referenced job may have been deleted."
                )
            cursor_created = cursor_job.created_at or datetime.min.replace(tzinfo=UTC)
            jobs = [
                job
                for job in jobs
                if (
                    (job.created_at or datetime.min.replace(tzinfo=UTC))
                    < cursor_created
                    or (
                        (job.created_at or datetime.min.replace(tzinfo=UTC))
                        == cursor_created
                        and job.id < cursor
                    )
                )
            ]
        return jobs[:limit]

    async def count_jobs(
        self,
        *,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> int:
        rows = await self.list_jobs(
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=start_date,
            end_date=end_date,
            limit=10_000_000,
            cursor=None,
            deployment_id=deployment_id,
        )
        return len(rows)

    async def get_stats(
        self,
        function: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> JobStatsSummary:
        rows = await self.list_jobs(
            function=function,
            start_date=start_date,
            end_date=end_date,
            limit=10_000_000,
            deployment_id=deployment_id,
        )
        total = len(rows)
        success_count = len([row for row in rows if row.status == "complete"])
        failure_count = len([row for row in rows if row.status == "failed"])
        cancelled_count = len([row for row in rows if row.status == "cancelled"])
        durations = [
            row.duration_ms
            for row in rows
            if row.started_at is not None
            and row.completed_at is not None
            and row.duration_ms is not None
        ]
        avg_duration = (
            round(float(sum(durations) / len(durations)), 2) if durations else None
        )
        success_rate = (success_count / total * 100.0) if total > 0 else 0.0
        return JobStatsSummary(
            total=total,
            success_count=success_count,
            failure_count=failure_count,
            cancelled_count=cancelled_count,
            success_rate=round(success_rate, 2),
            avg_duration_ms=avg_duration,
        )

    async def get_durations(
        self,
        *,
        function: str,
        start_date: datetime,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[float]:
        rows = await self.list_jobs(
            function=function,
            start_date=start_date,
            limit=10_000_000,
            deployment_id=deployment_id,
        )
        durations = [
            float(row.duration_ms)
            for row in rows
            if row.duration_ms is not None
            and row.started_at is not None
            and row.completed_at is not None
        ]
        durations.sort()
        return durations

    async def get_hourly_trends(
        self,
        *,
        start_date: datetime,
        end_date: datetime,
        function: str | None = None,
        functions: list[str] | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[JobHourlyTrendRow]:
        rows = await self.list_jobs(
            function=function,
            start_date=start_date,
            end_date=end_date,
            limit=10_000_000,
            deployment_id=deployment_id,
        )
        if function is None and functions is not None:
            allowed = set(functions)
            if not allowed:
                return []
            rows = [row for row in rows if row.function in allowed]

        buckets: dict[tuple[int, int, int, int, str], int] = defaultdict(int)
        for row in rows:
            if row.created_at is None:
                continue
            dt = row.created_at.astimezone(UTC)
            buckets[(dt.year, dt.month, dt.day, dt.hour, row.status)] += 1

        out = [
            JobHourlyTrendRow(yr=yr, mo=mo, dy=dy, hr=hr, status=status, cnt=count)
            for (yr, mo, dy, hr, status), count in buckets.items()
        ]
        out.sort(key=lambda row: (row.yr, row.mo, row.dy, row.hr, row.status))
        return out

    async def get_function_job_stats(
        self,
        *,
        start_date: datetime,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> dict[str, FunctionJobStats]:
        rows = await self.list_jobs(
            start_date=start_date,
            limit=10_000_000,
            deployment_id=deployment_id,
        )
        grouped: dict[str, list[Job]] = defaultdict(list)
        for row in rows:
            grouped[row.function].append(row)
        out: dict[str, FunctionJobStats] = {}
        for fn_key, fn_rows in grouped.items():
            fn_rows.sort(
                key=lambda row: (
                    row.completed_at or row.started_at or row.created_at or start_date
                ),
                reverse=True,
            )
            runs = len(fn_rows)
            successes = len([row for row in fn_rows if row.status == "complete"])
            failures = len([row for row in fn_rows if row.status == "failed"])
            durations = [
                row.duration_ms for row in fn_rows if row.duration_ms is not None
            ]
            avg_duration = (
                round(float(sum(durations) / len(durations)), 2) if durations else 0.0
            )
            latest = fn_rows[0]
            run_time = latest.completed_at or latest.started_at or latest.created_at
            out[fn_key] = FunctionJobStats(
                function=fn_key,
                runs=runs,
                successes=successes,
                failures=failures,
                avg_duration_ms=avg_duration,
                last_run_at=run_time.isoformat() if run_time else None,
                last_run_status=latest.status,
            )
        return out

    async def get_function_wait_stats(
        self,
        *,
        start_date: datetime,
        function: str | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> dict[str, FunctionWaitStats]:
        rows = await self.list_jobs(
            function=function,
            start_date=start_date,
            limit=10_000_000,
            deployment_id=deployment_id,
        )
        waits_by_fn: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.started_at is None or row.queue_wait_ms is None:
                continue
            if row.queue_wait_ms < 0:
                continue
            waits_by_fn[row.function].append(float(row.queue_wait_ms))

        out: dict[str, FunctionWaitStats] = {}
        for fn_key, waits in waits_by_fn.items():
            waits.sort()
            if not waits:
                continue
            p95_idx = min((len(waits) * 95 + 99) // 100 - 1, len(waits) - 1)
            out[fn_key] = FunctionWaitStats(
                function=fn_key,
                avg_wait_ms=round(sum(waits) / len(waits), 2),
                p95_wait_ms=round(waits[p95_idx], 2),
            )
        return out

    async def list_stuck_active_jobs(
        self,
        *,
        started_before: datetime,
        limit: int = 10,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[Job]:
        rows = await self.list_jobs(
            status="active",
            limit=10_000_000,
            deployment_id=deployment_id,
        )
        active = [
            row
            for row in rows
            if row.started_at is not None and row.started_at <= started_before
        ]
        active.sort(key=lambda row: row.started_at or started_before)
        return active[:limit]

    async def list_old_ids(
        self, retention_hours: int = 24, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[str]:
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        rows = await self.list_jobs(limit=10_000_000, deployment_id=deployment_id)
        return [row.id for row in rows if row.created_at and row.created_at < cutoff]

    async def delete_by_ids(
        self, ids: list[str], *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> int:
        if not ids:
            return 0
        deleted = 0
        for job_id in ids:
            job = await self.get_by_id(job_id, deployment_id=deployment_id)
            if job is None:
                continue
            removed = await self._redis.delete(_job_key(job_id))
            await self._redis.srem(_JOBS_SET, job_id)
            deleted += int(removed or 0)
        return deleted

    async def save_job(self, job: Job) -> None:
        await self._write_job(job)
