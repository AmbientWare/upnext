"""Repository classes for database operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, extract, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import Artifact, JobHistory, PendingArtifact


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
            dialect = self._session.bind.dialect.name  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            dialect = "sqlite"

        if dialect == "postgresql":
            return (
                extract("epoch", JobHistory.completed_at - JobHistory.started_at) * 1000
            )
        return (
            func.julianday(JobHistory.completed_at)
            - func.julianday(JobHistory.started_at)
        ) * 86400000

    async def record_job(self, data: dict[str, Any]) -> JobHistory:
        """
        Record a job to history.

        Args:
            data: Job data from API request

        Returns:
            Created JobHistory record
        """
        history = JobHistory(
            id=data["job_id"],
            function=data["function"],
            status=data["status"],
            created_at=data.get("created_at"),
            scheduled_at=data.get("scheduled_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            attempts=data.get("attempts", 1),
            max_retries=data.get("max_retries", 0),
            timeout=data.get("timeout"),
            worker_id=data.get("worker_id"),
            progress=data.get("progress", 0.0),
            kwargs=data.get("kwargs", {}),
            metadata_=data.get("metadata", {}),
            result=data.get("result"),
            error=data.get("error"),
        )
        self._session.add(history)
        return history

    async def get_by_id(
        self,
        job_id: str,
    ) -> JobHistory | None:
        """Get a job by ID."""
        query = select(JobHistory).where(JobHistory.id == job_id)

        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        *,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobHistory]:
        """
        List jobs with optional filtering.

        Args:
            function: Filter by function name
            status: Filter by status (single value or list)
            worker_id: Filter by worker ID
            start_date: Filter by created_at >= start_date
            end_date: Filter by created_at <= end_date
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of matching jobs
        """
        query = select(JobHistory).order_by(JobHistory.created_at.desc())

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

        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_stats(
        self,
        function: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Get aggregate statistics for jobs in a single query.

        Returns:
            Dict with total, success_count, failure_count, success_rate, avg_duration
        """
        query = select(
            func.count(JobHistory.id).label("total"),
            func.sum(case((JobHistory.status == "complete", 1), else_=0)).label(
                "success_count"
            ),
            func.sum(case((JobHistory.status == "failed", 1), else_=0)).label(
                "failure_count"
            ),
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
        success_rate = (success_count / total * 100) if total > 0 else 0.0

        return {
            "total": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "cancelled_count": total - success_count - failure_count,
            "success_rate": round(success_rate, 2),
        }

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
        return [row.duration_ms for row in result.all()]

    async def get_hourly_trends(
        self,
        *,
        start_date: datetime,
        end_date: datetime,
        function: str | None = None,
    ) -> list[Any]:
        """
        Get job counts grouped by hour and status using SQL aggregation.

        Returns rows of (year, month, day, hour, status, count).
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

        result = await self._session.execute(query)
        return list(result.all())

    async def get_function_job_stats(
        self,
        *,
        start_date: datetime,
    ) -> dict[str, dict[str, Any]]:
        """
        Get aggregated job stats per function in a single query.

        Uses window functions to compute both aggregate stats (counts, avg duration)
        and last-run info (status, timestamp) in one table scan, then filters to
        one row per function.

        Returns dict mapping function name to stats dict with:
        runs, successes, failures, avg_duration_ms, last_run_at, last_run_status
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

        stats: dict[str, dict[str, Any]] = {}
        for row in result.all():
            stats[row.function] = {
                "runs": row.runs,
                "successes": row.successes,
                "failures": row.failures,
                "avg_duration_ms": round(row.avg_duration_ms, 2)
                if row.avg_duration_ms
                else 0,
                "last_run_at": row.run_time.isoformat() if row.run_time else None,
                "last_run_status": row.status,
            }

        return stats

    async def cleanup_old_records(
        self,
        retention_days: int = 30,
    ) -> int:
        """
        Delete records older than retention period.

        Args:
            retention_days: Number of days to retain

        Returns:
            Number of deleted records
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        query = delete(JobHistory).where(JobHistory.created_at < cutoff)

        result = await self._session.execute(query)
        return result.rowcount if result.rowcount else 0  # type: ignore[return-value]


class ArtifactRepository:
    """Repository for artifact operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        job_id: str,
        name: str,
        artifact_type: str,
        data: Any | None = None,
        size_bytes: int | None = None,
        path: str | None = None,
    ) -> Artifact:
        """Create an artifact for a job."""
        artifact = Artifact(
            job_id=job_id,
            name=name,
            type=artifact_type,
            data=data,
            size_bytes=size_bytes,
            path=path,
        )
        self._session.add(artifact)
        await self._session.flush()
        return artifact

    async def create_pending(
        self,
        job_id: str,
        name: str,
        artifact_type: str,
        data: Any | None = None,
        size_bytes: int | None = None,
        path: str | None = None,
    ) -> PendingArtifact:
        """Create a pending artifact when the job row is not yet available."""
        pending = PendingArtifact(
            job_id=job_id,
            name=name,
            type=artifact_type,
            data=data,
            size_bytes=size_bytes,
            path=path,
        )
        self._session.add(pending)
        await self._session.flush()
        return pending

    async def promote_pending_for_job(self, job_id: str) -> int:
        """
        Promote pending artifacts into the main artifacts table for a job.

        Uses row-level locking where supported to avoid double-promotion.
        Returns number of promoted rows.
        """
        pending_query = (
            select(PendingArtifact)
            .where(PendingArtifact.job_id == job_id)
            .order_by(PendingArtifact.id.asc())
            .with_for_update(skip_locked=True)
        )
        pending_result = await self._session.execute(pending_query)
        pending_rows = list(pending_result.scalars().all())
        return await self._promote_pending_rows(pending_rows)

    async def promote_ready_pending(self, *, limit: int = 500) -> int:
        """
        Promote pending artifacts whose job rows now exist.

        This is used as a background safety net when event-triggered promotion
        was missed for any reason.
        """
        if limit <= 0:
            return 0

        ready_ids_query = (
            select(PendingArtifact.id)
            .where(
                select(JobHistory.id)
                .where(JobHistory.id == PendingArtifact.job_id)
                .exists()
            )
            .order_by(PendingArtifact.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ready_ids_result = await self._session.execute(ready_ids_query)
        ready_ids = list(ready_ids_result.scalars().all())
        if not ready_ids:
            return 0

        ready_rows_query = (
            select(PendingArtifact)
            .where(PendingArtifact.id.in_(ready_ids))
            .order_by(PendingArtifact.id.asc())
        )
        ready_rows_result = await self._session.execute(ready_rows_query)
        ready_rows = list(ready_rows_result.scalars().all())
        return await self._promote_pending_rows(ready_rows)

    async def cleanup_stale_pending(self, *, retention_hours: int = 24) -> int:
        """Delete pending artifacts older than retention window."""
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        result = await self._session.execute(
            delete(PendingArtifact).where(PendingArtifact.created_at < cutoff)
        )
        return result.rowcount if result.rowcount else 0  # type: ignore[return-value]

    async def _promote_pending_rows(
        self, pending_rows: list[PendingArtifact]
    ) -> int:
        """Promote rows into artifacts and remove source pending rows atomically."""
        if not pending_rows:
            return 0

        pending_ids = [row.id for row in pending_rows]
        for row in pending_rows:
            self._session.add(
                Artifact(
                    job_id=row.job_id,
                    name=row.name,
                    type=row.type,
                    size_bytes=row.size_bytes,
                    data=row.data,
                    path=row.path,
                    created_at=row.created_at,
                )
            )

        await self._session.flush()
        await self._session.execute(
            delete(PendingArtifact).where(PendingArtifact.id.in_(pending_ids))
        )
        return len(pending_rows)

    async def get_by_id(self, artifact_id: int) -> Artifact | None:
        """Get an artifact by ID."""
        query = select(Artifact).where(Artifact.id == artifact_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_job(self, job_id: str) -> list[Artifact]:
        """List all artifacts for a job."""
        query = (
            select(Artifact)
            .where(Artifact.job_id == job_id)
            .order_by(Artifact.created_at.desc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def delete(self, artifact_id: int) -> bool:
        """Delete an artifact by ID."""
        query = delete(Artifact).where(Artifact.id == artifact_id)
        result: CursorResult[Any] = await self._session.execute(query)  # type: ignore[assignment]
        return (result.rowcount or 0) > 0
