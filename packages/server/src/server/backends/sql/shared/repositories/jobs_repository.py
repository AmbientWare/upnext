"""Repository classes for database operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

from shared.keys import DEFAULT_WORKSPACE_ID
from sqlalchemy import and_, case, delete, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

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
from server.backends.sql.shared.tables import JobHistoryTable


class PostgresJobRepository(BaseJobRepository):
    """
    Repository for job history operations.

    Provides methods for recording completed jobs and querying history.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_model(payload: object) -> Job:
        if not isinstance(payload, JobHistoryTable):
            return BaseJobRepository._to_model(payload)
        row = payload
        return Job(
            id=row.id,
            workspace_id=row.workspace_id,
            function=row.function,
            function_name=row.function_name,
            job_key=row.job_key,
            job_type=row.job_type,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            scheduled_at=row.scheduled_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            queue_wait_ms=row.queue_wait_ms,
            attempts=row.attempts,
            max_retries=row.max_retries,
            timeout=row.timeout,
            worker_id=row.worker_id,
            parent_id=row.parent_id,
            root_id=row.root_id,
            progress=row.progress,
            kwargs=dict(row.kwargs or {}),
            schedule=row.schedule,
            cron_window_at=row.cron_window_at,
            startup_reconciled=row.startup_reconciled,
            startup_policy=row.startup_policy,
            checkpoint=row.checkpoint,
            checkpoint_at=row.checkpoint_at,
            event_pattern=row.event_pattern,
            event_handler_name=row.event_handler_name,
            result=row.result,
            error=row.error,
        )

    @staticmethod
    def _apply_job_to_row(row: JobHistoryTable, job: Job) -> None:
        row.id = job.id
        row.workspace_id = job.workspace_id
        row.function = job.function
        row.function_name = job.function_name
        row.job_key = job.job_key
        row.job_type = job.job_type
        row.status = job.status
        now = datetime.now(UTC)
        row.created_at = job.created_at or now
        row.updated_at = job.updated_at or now
        row.scheduled_at = job.scheduled_at
        row.started_at = job.started_at
        row.completed_at = job.completed_at
        row.queue_wait_ms = job.queue_wait_ms
        row.attempts = job.attempts
        row.max_retries = job.max_retries
        row.timeout = job.timeout
        row.worker_id = job.worker_id
        row.parent_id = job.parent_id
        row.root_id = job.root_id
        row.progress = job.progress
        row.kwargs = dict(job.kwargs)
        row.schedule = job.schedule
        row.cron_window_at = job.cron_window_at
        row.startup_reconciled = job.startup_reconciled
        row.startup_policy = job.startup_policy
        row.checkpoint = job.checkpoint
        row.checkpoint_at = job.checkpoint_at
        row.event_pattern = job.event_pattern
        row.event_handler_name = job.event_handler_name
        row.result = job.result
        row.error = job.error

    def _duration_ms_expr(self):
        """SQL expression for job duration in milliseconds (dialect-aware)."""
        try:
            bind = self._session.get_bind()
            dialect = bind.dialect.name if bind is not None else "sqlite"
        except Exception:
            dialect = "sqlite"

        if dialect == "postgresql":
            return (
                extract(
                    "epoch", JobHistoryTable.completed_at - JobHistoryTable.started_at
                )
                * 1000
            )

        return (
            func.julianday(JobHistoryTable.completed_at)
            - func.julianday(JobHistoryTable.started_at)
        ) * 86400000

    async def record_job(self, data: JobRecordCreate | Mapping[str, object]) -> Job:
        """
        Record a job to history.

        Args:
            data: Typed payload or mapping accepted by JobRecordCreate

        Returns:
            Created JobHistoryTable record
        """
        payload = (
            data
            if isinstance(data, JobRecordCreate)
            else JobRecordCreate.model_validate(data)
        )
        history = JobHistoryTable(**payload.model_dump(mode="python"))
        self._session.add(history)
        return self._to_model(history)

    async def get_by_id(
        self,
        id: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Job | None:
        """Get a job by ID."""
        query = select(JobHistoryTable).where(
            JobHistoryTable.id == id,
            JobHistoryTable.workspace_id == workspace_id,
        )

        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_model(row)

    async def list_job_subtree(
        self,
        id: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[Job]:
        """
        List a job and all recursive descendants by parent_id lineage.

        Descendants are discovered breadth-first for stable query behavior
        across SQLite/PostgreSQL backends.
        """
        root = await self.get_by_id(id, workspace_id=workspace_id)
        if root is None:
            return []

        parent_id_expr = JobHistoryTable.parent_id
        jobs_by_id: dict[str, Job] = {root.id: root}
        frontier: set[str] = {root.id}

        while frontier:
            query = select(JobHistoryTable).where(
                parent_id_expr.in_(list(frontier)),
                JobHistoryTable.workspace_id == workspace_id,
            )
            result = await self._session.execute(query)
            children = list(result.scalars().all())

            next_frontier: set[str] = set()
            for child in children:
                if child.id in jobs_by_id:
                    continue
                jobs_by_id[child.id] = self._to_model(child)
                next_frontier.add(child.id)

            frontier = next_frontier

        def timeline_sort_key(job: Job) -> tuple[datetime, str]:
            return (
                job.started_at
                or job.created_at
                or job.scheduled_at
                or job.completed_at
                or datetime.min.replace(tzinfo=UTC),
                job.id,
            )

        return sorted(jobs_by_id.values(), key=timeline_sort_key)

    @staticmethod
    def _apply_job_list_filters(
        query: Select[tuple[object]],
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Select[tuple[object]]:
        """Apply common filters for job list/count queries."""
        query = query.where(JobHistoryTable.workspace_id == workspace_id)
        if function:
            query = query.where(JobHistoryTable.function == function)
        if isinstance(status, str) and status:
            query = query.where(JobHistoryTable.status == status)
        elif isinstance(status, list) and status:
            query = query.where(JobHistoryTable.status.in_(status))
        if worker_id:
            query = query.where(JobHistoryTable.worker_id == worker_id)
        if start_date:
            query = query.where(JobHistoryTable.created_at >= start_date)
        if end_date:
            query = query.where(JobHistoryTable.created_at <= end_date)
        return query

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
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[Job]:
        """
        List jobs with optional filtering using cursor-based pagination.

        Args:
            function: Filter by function key
            status: Filter by status (single value or list)
            worker_id: Filter by worker ID
            start_date: Filter by created_at >= start_date
            end_date: Filter by created_at <= end_date
            limit: Maximum results to return
            cursor: Job ID to paginate after (returns jobs older than this)

        Returns:
            List of matching jobs
        """
        query = select(JobHistoryTable).order_by(
            JobHistoryTable.created_at.desc(),
            JobHistoryTable.id.desc(),
        )
        query = self._apply_job_list_filters(
            cast(Select[tuple[object]], query),
            workspace_id=workspace_id,
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=start_date,
            end_date=end_date,
        )

        if cursor:
            cursor_job = await self.get_by_id(cursor, workspace_id=workspace_id)
            if cursor_job is None:
                raise InvalidCursorError(
                    f"Cursor job '{cursor}' not found. "
                    "The referenced job may have been deleted."
                )
            if cursor_job.created_at:
                query = query.where(
                    (JobHistoryTable.created_at < cursor_job.created_at)
                    | (
                        (JobHistoryTable.created_at == cursor_job.created_at)
                        & (JobHistoryTable.id < cursor)
                    )
                )

        query = query.limit(limit)

        result = await self._session.execute(query)
        jobs: list[Job] = []
        for row in result.scalars().all():
            if isinstance(row, JobHistoryTable):
                jobs.append(self._to_model(row))
        return jobs

    async def count_jobs(
        self,
        *,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> int:
        """Count jobs with the same filters used by list_jobs."""
        query = select(func.count(JobHistoryTable.id))
        query = self._apply_job_list_filters(
            cast(Select[tuple[object]], query),
            workspace_id=workspace_id,
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=start_date,
            end_date=end_date,
        )
        result = await self._session.execute(query)
        raw_count = result.scalar()
        if raw_count is None:
            return 0
        if isinstance(raw_count, bool):
            return int(raw_count)
        if isinstance(raw_count, int):
            return raw_count
        if isinstance(raw_count, (float, str, bytes)):
            return int(raw_count)
        return 0

    async def get_stats(
        self,
        function: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> JobStatsSummary:
        """
        Get aggregate statistics for jobs in a single query.

        Returns:
            Typed summary with counts, success rate, and average duration.
        """
        duration_expr = self._duration_ms_expr()
        query = select(
            func.count(JobHistoryTable.id).label("total"),
            func.sum(case((JobHistoryTable.status == "complete", 1), else_=0)).label(
                "success_count"
            ),
            func.sum(case((JobHistoryTable.status == "failed", 1), else_=0)).label(
                "failure_count"
            ),
            func.sum(case((JobHistoryTable.status == "cancelled", 1), else_=0)).label(
                "cancelled_count"
            ),
            func.avg(
                case(
                    (
                        and_(
                            JobHistoryTable.started_at.is_not(None),
                            JobHistoryTable.completed_at.is_not(None),
                        ),
                        duration_expr,
                    ),
                    else_=None,
                )
            ).label("avg_duration_ms"),
        )

        query = query.where(JobHistoryTable.workspace_id == workspace_id)
        if function:
            query = query.where(JobHistoryTable.function == function)
        if start_date:
            query = query.where(JobHistoryTable.created_at >= start_date)
        if end_date:
            query = query.where(JobHistoryTable.created_at <= end_date)

        result = await self._session.execute(query)
        row = result.one()

        total = row.total or 0
        success_count = row.success_count or 0
        failure_count = row.failure_count or 0
        cancelled_count = row.cancelled_count or 0
        avg_duration_ms = (
            round(float(row.avg_duration_ms), 2)
            if row.avg_duration_ms is not None
            else None
        )
        success_rate = (success_count / total * 100) if total > 0 else 0.0

        return JobStatsSummary(
            total=total,
            success_count=success_count,
            failure_count=failure_count,
            cancelled_count=cancelled_count,
            success_rate=round(success_rate, 2),
            avg_duration_ms=avg_duration_ms,
        )

    async def get_durations(
        self,
        *,
        function: str,
        start_date: datetime,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[float]:
        """Return all completed job durations (ms) for a function since start_date."""
        duration_expr = self._duration_ms_expr()

        query = (
            select(duration_expr.label("duration_ms"))
            .where(
                JobHistoryTable.workspace_id == workspace_id,
                JobHistoryTable.function == function,
                JobHistoryTable.created_at >= start_date,
                JobHistoryTable.started_at.isnot(None),
                JobHistoryTable.completed_at.isnot(None),
            )
            .order_by(duration_expr)
        )

        result = await self._session.execute(query)
        durations: list[float] = []
        for row in result.all():
            duration_ms = row.duration_ms
            if duration_ms is None:
                continue
            durations.append(float(duration_ms))
        return durations

    async def get_hourly_trends(
        self,
        *,
        start_date: datetime,
        end_date: datetime,
        function: str | None = None,
        functions: list[str] | None = None,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[JobHourlyTrendRow]:
        """
        Get job counts grouped by hour and status using SQL aggregation.
        """
        year_col = extract("year", JobHistoryTable.created_at)
        month_col = extract("month", JobHistoryTable.created_at)
        day_col = extract("day", JobHistoryTable.created_at)
        hour_col = extract("hour", JobHistoryTable.created_at)

        query = (
            select(
                year_col.label("yr"),
                month_col.label("mo"),
                day_col.label("dy"),
                hour_col.label("hr"),
                JobHistoryTable.status,
                func.count(JobHistoryTable.id).label("cnt"),
            )
            .where(
                JobHistoryTable.workspace_id == workspace_id,
                JobHistoryTable.created_at >= start_date,
                JobHistoryTable.created_at <= end_date,
            )
            .group_by(year_col, month_col, day_col, hour_col, JobHistoryTable.status)
            .order_by(year_col, month_col, day_col, hour_col)
        )

        if function:
            query = query.where(JobHistoryTable.function == function)
        elif functions is not None:
            if not functions:
                return []
            query = query.where(JobHistoryTable.function.in_(functions))

        result = await self._session.execute(query)
        return [
            JobHourlyTrendRow(
                yr=int(row.yr),
                mo=int(row.mo),
                dy=int(row.dy),
                hr=int(row.hr),
                status=str(row.status),
                cnt=int(row.cnt or 0),
            )
            for row in result.all()
        ]

    async def get_function_job_stats(
        self,
        *,
        start_date: datetime,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict[str, FunctionJobStats]:
        """
        Get aggregated job stats per function key in a single query.

        Uses window functions to compute both aggregate stats (counts, avg duration)
        and last-run info (status, timestamp) in one table scan, then filters to
        one row per function.

        Returns dict mapping function key to `FunctionJobStats`.
        """
        duration_expr = self._duration_ms_expr()

        run_time_col = func.coalesce(
            JobHistoryTable.completed_at,
            JobHistoryTable.started_at,
            JobHistoryTable.created_at,
        )
        partition = JobHistoryTable.function

        # Single subquery: window aggregates + ROW_NUMBER in one table scan
        subq = (
            select(
                JobHistoryTable.function,
                JobHistoryTable.status,
                run_time_col.label("run_time"),
                func.count(JobHistoryTable.id)
                .over(partition_by=partition)
                .label("runs"),
                func.sum(case((JobHistoryTable.status == "complete", 1), else_=0))
                .over(partition_by=partition)
                .label("successes"),
                func.sum(case((JobHistoryTable.status == "failed", 1), else_=0))
                .over(partition_by=partition)
                .label("failures"),
                func.avg(
                    case(
                        (
                            JobHistoryTable.started_at.isnot(None)
                            & JobHistoryTable.completed_at.isnot(None),
                            duration_expr,
                        ),
                        else_=None,
                    )
                )
                .over(partition_by=partition)
                .label("avg_duration_ms"),
                func.row_number()
                .over(
                    partition_by=partition,
                    order_by=run_time_col.desc(),
                )
                .label("rn"),
            )
            .where(
                JobHistoryTable.created_at >= start_date,
                JobHistoryTable.workspace_id == workspace_id,
            )
            .subquery()
        )

        # Filter to latest row per function — carries both aggregates and last-run info
        query = select(
            subq.c.function,
            subq.c.status,
            subq.c.run_time,
            subq.c.runs,
            subq.c.successes,
            subq.c.failures,
            subq.c.avg_duration_ms,
        ).where(subq.c.rn == 1)

        result = await self._session.execute(query)

        stats: dict[str, FunctionJobStats] = {}
        for row in result.all():
            function_key = str(row.function)
            runs = int(row.runs or 0)
            successes = int(row.successes or 0)
            failures = int(row.failures or 0)
            avg_duration_ms = 0.0
            if row.avg_duration_ms is not None:
                avg_duration_ms = round(float(row.avg_duration_ms), 2)

            stats[function_key] = FunctionJobStats(
                function=function_key,
                runs=runs,
                successes=successes,
                failures=failures,
                avg_duration_ms=avg_duration_ms,
                last_run_at=row.run_time.isoformat() if row.run_time else None,
                last_run_status=str(row.status) if row.status is not None else None,
            )

        return stats

    async def get_function_wait_stats(
        self,
        *,
        start_date: datetime,
        function: str | None = None,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> dict[str, FunctionWaitStats]:
        """
        Compute per-function queue wait metrics from persisted job columns.
        """
        query = select(JobHistoryTable.function, JobHistoryTable.queue_wait_ms).where(
            JobHistoryTable.workspace_id == workspace_id,
            JobHistoryTable.created_at >= start_date,
            JobHistoryTable.started_at.isnot(None),
            JobHistoryTable.queue_wait_ms.isnot(None),
        )
        if function:
            query = query.where(JobHistoryTable.function == function)

        result = await self._session.execute(query)
        waits_by_function: dict[str, list[float]] = {}

        for row in result.all():
            if row.queue_wait_ms is None:
                continue
            wait_ms = float(row.queue_wait_ms)
            if wait_ms < 0:
                continue
            waits_by_function.setdefault(str(row.function), []).append(wait_ms)

        out: dict[str, FunctionWaitStats] = {}
        for fn_key, waits in waits_by_function.items():
            if not waits:
                continue
            waits.sort()
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
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[Job]:
        """List active jobs that have been running since before `started_before`."""
        query = (
            select(JobHistoryTable)
            .where(
                JobHistoryTable.workspace_id == workspace_id,
                JobHistoryTable.status == "active",
                JobHistoryTable.started_at.isnot(None),
                JobHistoryTable.started_at <= started_before,
            )
            .order_by(JobHistoryTable.started_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return [self._to_model(row) for row in result.scalars().all()]

    async def list_old_ids(
        self, retention_hours: int = 24, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[str]:
        """Return job IDs older than retention cutoff."""
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        query = select(JobHistoryTable.id).where(
            JobHistoryTable.created_at < cutoff,
            JobHistoryTable.workspace_id == workspace_id,
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def delete_by_ids(
        self, ids: list[str], *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> int:
        """Delete jobs by explicit ID set."""
        if not ids:
            return 0
        query = delete(JobHistoryTable).where(
            JobHistoryTable.id.in_(ids),
            JobHistoryTable.workspace_id == workspace_id,
        )
        result = await self._session.execute(query)
        return int(result.rowcount or 0)  # type: ignore

    async def save_job(self, job: Job) -> None:
        existing_row = await self._session.get(JobHistoryTable, job.id)
        if existing_row is None:
            existing_row = JobHistoryTable(id=job.id)
            self._session.add(existing_row)
        self._apply_job_to_row(existing_row, job)
        await self._session.flush()
