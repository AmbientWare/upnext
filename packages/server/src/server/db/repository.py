"""Repository classes for database operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from server.db.models import JobHistory
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class JobRepository:
    """
    Repository for job history operations.

    Provides methods for recording completed jobs and querying history.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_job(self, data: dict[str, Any]) -> JobHistory:
        """
        Record a completed job to history.

        Args:
            data: Job data from API request

        Returns:
            Created JobHistory record
        """
        history = JobHistory(
            id=data["job_id"],
            key=data.get("key", data["job_id"]),
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
            state_history=data.get("state_history", []),
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
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobHistory]:
        """
        List jobs with optional filtering.

        Args:
            function: Filter by function name
            status: Filter by status
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
        if status:
            query = query.where(JobHistory.status == status)
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
        Get aggregate statistics for jobs.

        Returns:
            Dict with total, success_count, failure_count, success_rate, avg_duration
        """
        # Build base query
        base_filter = []
        if function:
            base_filter.append(JobHistory.function == function)
        if start_date:
            base_filter.append(JobHistory.created_at >= start_date)
        if end_date:
            base_filter.append(JobHistory.created_at <= end_date)

        # Total count
        total_query = select(func.count(JobHistory.id))
        if base_filter:
            total_query = total_query.where(*base_filter)
        total_result = await self._session.execute(total_query)
        total = total_result.scalar() or 0

        # Success count
        success_query = select(func.count(JobHistory.id)).where(
            JobHistory.status == "complete",
            *base_filter,
        )
        success_result = await self._session.execute(success_query)
        success_count = success_result.scalar() or 0

        # Failure count
        failure_query = select(func.count(JobHistory.id)).where(
            JobHistory.status == "failed",
            *base_filter,
        )
        failure_result = await self._session.execute(failure_query)
        failure_count = failure_result.scalar() or 0

        # Calculate success rate
        success_rate = (success_count / total * 100) if total > 0 else 0.0

        return {
            "total": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "cancelled_count": total - success_count - failure_count,
            "success_rate": round(success_rate, 2),
        }

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
