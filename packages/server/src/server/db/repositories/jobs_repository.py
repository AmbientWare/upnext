"""Repository classes for database operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import and_, case, delete, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from server.db.repositories.models import (
    FunctionJobStats,
    FunctionWaitStats,
    JobHourlyTrendRow,
    JobRecordCreate,
    JobStatsSummary,
)
from server.db.tables import JobHistory

SelectT = TypeVar("SelectT", bound=Select[Any])


class InvalidCursorError(ValueError):
    """Raised when a pagination cursor references a non-existent job."""


class JobRepository:
    """
    Repository for job history operations.

    Provides methods for recording completed jobs and querying history.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _duration_ms_expr(self):
        """SQL expression for job duration in milliseconds (dialect-aware)."""
        try:
            bind = self._session.get_bind()
            dialect = bind.dialect.name if bind is not None else "sqlite"
        except Exception:
            dialect = "sqlite"

        if dialect == "postgresql":
            return (
                extract("epoch", JobHistory.completed_at - JobHistory.started_at) * 1000
            )

        return (
            func.julianday(JobHistory.completed_at)
            - func.julianday(JobHistory.started_at)
        ) * 86400000

    async def record_job(
        self, data: JobRecordCreate | Mapping[str, object]
    ) -> JobHistory:
        """
        Record a job to history.

        Args:
            data: Typed payload or mapping accepted by JobRecordCreate

        Returns:
            Created JobHistory record
        """
        payload = (
            data
            if isinstance(data, JobRecordCreate)
            else JobRecordCreate.model_validate(data)
        )
        history = JobHistory(**payload.model_dump(mode="python"))
        self._session.add(history)
        return history

    async def get_by_id(
        self,
        id: str,
    ) -> JobHistory | None:
        """Get a job by ID."""
        query = select(JobHistory).where(JobHistory.id == id)

        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def list_job_subtree(self, id: str) -> list[JobHistory]:
        """
        List a job and all recursive descendants by parent_id lineage.

        Descendants are discovered breadth-first for stable query behavior
        across SQLite/PostgreSQL backends.
        """
        root = await self.get_by_id(id)
        if root is None:
            return []

        parent_id_expr = JobHistory.parent_id
        jobs_by_id: dict[str, JobHistory] = {root.id: root}
        frontier: set[str] = {root.id}

        while frontier:
            query = select(JobHistory).where(parent_id_expr.in_(list(frontier)))
            result = await self._session.execute(query)
            children = list(result.scalars().all())

            next_frontier: set[str] = set()
            for child in children:
                if child.id in jobs_by_id:
                    continue
                jobs_by_id[child.id] = child
                next_frontier.add(child.id)

            frontier = next_frontier

        def timeline_sort_key(job: JobHistory) -> tuple[datetime, str]:
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
        query: SelectT,
        *,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> SelectT:
        """Apply common filters for job list/count queries."""
        if function:
            query = query.where(JobHistory.function == function)
        if isinstance(status, str) and status:
            query = query.where(JobHistory.status == status)
        elif isinstance(status, list) and status:
            query = query.where(JobHistory.status.in_(status))
        if worker_id:
            query = query.where(JobHistory.worker_id == worker_id)
        if start_date:
            query = query.where(JobHistory.created_at >= start_date)
        if end_date:
            query = query.where(JobHistory.created_at <= end_date)
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
    ) -> list[JobHistory]:
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
        query = select(JobHistory).order_by(
            JobHistory.created_at.desc(),
            JobHistory.id.desc(),
        )
        query = self._apply_job_list_filters(
            query,
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=start_date,
            end_date=end_date,
        )

        if cursor:
            cursor_job = await self.get_by_id(cursor)
            if cursor_job is None:
                raise InvalidCursorError(
                    f"Cursor job '{cursor}' not found. "
                    "The referenced job may have been deleted."
                )
            if cursor_job.created_at:
                query = query.where(
                    (JobHistory.created_at < cursor_job.created_at)
                    | (
                        (JobHistory.created_at == cursor_job.created_at)
                        & (JobHistory.id < cursor)
                    )
                )

        query = query.limit(limit)

        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_jobs(
        self,
        *,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Count jobs with the same filters used by list_jobs."""
        query = select(func.count(JobHistory.id))
        query = self._apply_job_list_filters(
            query,
            function=function,
            status=status,
            worker_id=worker_id,
            start_date=start_date,
            end_date=end_date,
        )
        result = await self._session.execute(query)
        return int(result.scalar() or 0)

    async def get_stats(
        self,
        function: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> JobStatsSummary:
        """
        Get aggregate statistics for jobs in a single query.

        Returns:
            Typed summary with counts, success rate, and average duration.
        """
        duration_expr = self._duration_ms_expr()
        query = select(
            func.count(JobHistory.id).label("total"),
            func.sum(case((JobHistory.status == "complete", 1), else_=0)).label(
                "success_count"
            ),
            func.sum(case((JobHistory.status == "failed", 1), else_=0)).label(
                "failure_count"
            ),
            func.avg(
                case(
                    (
                        and_(
                            JobHistory.started_at.is_not(None),
                            JobHistory.completed_at.is_not(None),
                        ),
                        duration_expr,
                    ),
                    else_=None,
                )
            ).label("avg_duration_ms"),
        )

        if function:
            query = query.where(JobHistory.function == function)
        if start_date:
            query = query.where(JobHistory.created_at >= start_date)
        if end_date:
            query = query.where(JobHistory.created_at <= end_date)

        result = await self._session.execute(query)
        row = result.one()

        total = row.total or 0
        success_count = row.success_count or 0
        failure_count = row.failure_count or 0
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
            cancelled_count=total - success_count - failure_count,
            success_rate=round(success_rate, 2),
            avg_duration_ms=avg_duration_ms,
        )

    async def get_durations(
        self,
        *,
        function: str,
        start_date: datetime,
    ) -> list[float]:
        """Return all completed job durations (ms) for a function since start_date."""
        duration_expr = self._duration_ms_expr()

        query = (
            select(duration_expr.label("duration_ms"))
            .where(
                JobHistory.function == function,
                JobHistory.created_at >= start_date,
                JobHistory.started_at.isnot(None),
                JobHistory.completed_at.isnot(None),
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
    ) -> list[JobHourlyTrendRow]:
        """
        Get job counts grouped by hour and status using SQL aggregation.
        """
        year_col = extract("year", JobHistory.created_at)
        month_col = extract("month", JobHistory.created_at)
        day_col = extract("day", JobHistory.created_at)
        hour_col = extract("hour", JobHistory.created_at)

        query = (
            select(
                year_col.label("yr"),
                month_col.label("mo"),
                day_col.label("dy"),
                hour_col.label("hr"),
                JobHistory.status,
                func.count(JobHistory.id).label("cnt"),
            )
            .where(
                JobHistory.created_at >= start_date,
                JobHistory.created_at <= end_date,
            )
            .group_by(year_col, month_col, day_col, hour_col, JobHistory.status)
            .order_by(year_col, month_col, day_col, hour_col)
        )

        if function:
            query = query.where(JobHistory.function == function)
        elif functions is not None:
            if not functions:
                return []
            query = query.where(JobHistory.function.in_(functions))

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
            JobHistory.completed_at, JobHistory.started_at, JobHistory.created_at
        )
        partition = JobHistory.function

        # Single subquery: window aggregates + ROW_NUMBER in one table scan
        subq = (
            select(
                JobHistory.function,
                JobHistory.status,
                run_time_col.label("run_time"),
                func.count(JobHistory.id).over(partition_by=partition).label("runs"),
                func.sum(case((JobHistory.status == "complete", 1), else_=0))
                .over(partition_by=partition)
                .label("successes"),
                func.sum(case((JobHistory.status == "failed", 1), else_=0))
                .over(partition_by=partition)
                .label("failures"),
                func.avg(
                    case(
                        (
                            JobHistory.started_at.isnot(None)
                            & JobHistory.completed_at.isnot(None),
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
            .where(JobHistory.created_at >= start_date)
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
    ) -> dict[str, FunctionWaitStats]:
        """
        Compute per-function queue wait metrics from persisted job columns.
        """
        query = select(JobHistory.function, JobHistory.queue_wait_ms).where(
            JobHistory.created_at >= start_date,
            JobHistory.started_at.isnot(None),
            JobHistory.queue_wait_ms.isnot(None),
        )
        if function:
            query = query.where(JobHistory.function == function)

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
    ) -> list[JobHistory]:
        """List active jobs that have been running since before `started_before`."""
        query = (
            select(JobHistory)
            .where(
                JobHistory.status == "active",
                JobHistory.started_at.isnot(None),
                JobHistory.started_at <= started_before,
            )
            .order_by(JobHistory.started_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_old_ids(self, retention_days: int = 30) -> list[str]:
        """Return job IDs older than retention cutoff."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        query = select(JobHistory.id).where(JobHistory.created_at < cutoff)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def delete_by_ids(self, ids: list[str]) -> int:
        """Delete jobs by explicit ID set."""
        if not ids:
            return 0
        query = delete(JobHistory).where(JobHistory.id.in_(ids))
        result = await self._session.execute(query)
        return int(result.rowcount or 0)  # type: ignore
