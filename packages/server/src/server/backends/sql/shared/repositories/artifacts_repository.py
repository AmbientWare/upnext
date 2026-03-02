"""Repository classes for database operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.backends.base.repositories import BaseArtifactRepository
from server.backends.base.repository_models import (
    ArtifactRecord,
    PendingArtifactRecord,
)
from server.backends.base.utils import infer_artifact_metadata
from server.backends.sql.shared.tables import (
    ArtifactTable,
    JobHistoryTable,
    PendingArtifactTable,
)


class PostgresArtifactRepository(BaseArtifactRepository):
    """Repository for artifact operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_artifact_record(artifact: ArtifactTable) -> ArtifactRecord:
        """Convert ORM ArtifactTable rows into typed repository records."""
        return ArtifactRecord(
            id=artifact.id,
            job_id=artifact.job_id,
            name=artifact.name,
            type=artifact.type,
            size_bytes=artifact.size_bytes,
            content_type=artifact.content_type,
            sha256=artifact.sha256,
            storage_backend=artifact.storage_backend,
            storage_key=artifact.storage_key,
            status=artifact.status,
            error=artifact.error,
            created_at=artifact.created_at,
        )

    @staticmethod
    def _to_pending_record(pending: PendingArtifactTable) -> PendingArtifactRecord:
        """Convert ORM PendingArtifactTable rows into typed repository records."""
        return PendingArtifactRecord(
            id=pending.id,
            job_id=pending.job_id,
            name=pending.name,
            type=pending.type,
            size_bytes=pending.size_bytes,
            content_type=pending.content_type,
            sha256=pending.sha256,
            storage_backend=pending.storage_backend,
            storage_key=pending.storage_key,
            status=pending.status,
            error=pending.error,
            created_at=pending.created_at,
        )

    async def create(
        self,
        job_id: str,
        name: str,
        artifact_type: str,
        data: object | None = None,
        size_bytes: int | None = None,
        path: str | None = None,
        content_type: str | None = None,
        sha256: str | None = None,
        storage_backend: str = "local",
        storage_key: str = "",
        status: str = "available",
        error: str | None = None,
    ) -> ArtifactRecord:
        """Create an artifact for a job."""
        size_bytes, content_type = infer_artifact_metadata(
            data=data,
            path=path,
            size_bytes=size_bytes,
            content_type=content_type,
        )

        artifact = ArtifactTable(
            job_id=job_id,
            name=name,
            type=artifact_type,
            size_bytes=size_bytes,
            content_type=content_type,
            sha256=sha256,
            storage_backend=storage_backend,
            storage_key=storage_key,
            status=status,
            error=error,
        )
        self._session.add(artifact)
        await self._session.flush()
        return self._to_artifact_record(artifact)

    async def create_pending(
        self,
        job_id: str,
        name: str,
        artifact_type: str,
        data: object | None = None,
        size_bytes: int | None = None,
        path: str | None = None,
        content_type: str | None = None,
        sha256: str | None = None,
        storage_backend: str = "local",
        storage_key: str = "",
        status: str = "queued",
        error: str | None = None,
    ) -> PendingArtifactRecord:
        """Create a pending artifact when the job row is not yet available."""
        size_bytes, content_type = infer_artifact_metadata(
            data=data,
            path=path,
            size_bytes=size_bytes,
            content_type=content_type,
        )

        pending = PendingArtifactTable(
            job_id=job_id,
            name=name,
            type=artifact_type,
            size_bytes=size_bytes,
            content_type=content_type,
            sha256=sha256,
            storage_backend=storage_backend,
            storage_key=storage_key,
            status=status,
            error=error,
        )
        self._session.add(pending)
        await self._session.flush()
        return self._to_pending_record(pending)

    async def promote_pending_for_job(self, job_id: str) -> int:
        """
        Promote pending artifacts into the main artifacts table for a job.

        Uses row-level locking where supported to avoid double-promotion.
        Returns number of promoted rows.
        """
        pending_query = (
            select(PendingArtifactTable)
            .where(PendingArtifactTable.job_id == job_id)
            .order_by(
                PendingArtifactTable.created_at.asc(), PendingArtifactTable.id.asc()
            )
            .with_for_update(skip_locked=True)
        )
        pending_result = await self._session.execute(pending_query)
        pending_rows = list(pending_result.scalars().all())
        return await self._promote_pending_rows(pending_rows)

    async def promote_pending_for_job_with_artifacts(
        self, job_id: str
    ) -> list[ArtifactRecord]:
        """Promote pending artifacts for one job and return promoted rows."""
        pending_query = (
            select(PendingArtifactTable)
            .where(PendingArtifactTable.job_id == job_id)
            .order_by(
                PendingArtifactTable.created_at.asc(), PendingArtifactTable.id.asc()
            )
            .with_for_update(skip_locked=True)
        )
        pending_result = await self._session.execute(pending_query)
        pending_rows = list(pending_result.scalars().all())
        return await self._promote_pending_rows_with_artifacts(pending_rows)

    async def promote_ready_pending(self, *, limit: int = 500) -> int:
        """
        Promote pending artifacts whose job rows now exist.

        This is used as a background safety net when event-triggered promotion
        was missed for any reason.
        """
        if limit <= 0:
            return 0

        ready_ids_query = (
            select(PendingArtifactTable.id)
            .where(
                select(JobHistoryTable.id)
                .where(JobHistoryTable.id == PendingArtifactTable.job_id)
                .exists()
            )
            .order_by(
                PendingArtifactTable.created_at.asc(), PendingArtifactTable.id.asc()
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ready_ids_result = await self._session.execute(ready_ids_query)
        ready_ids = list(ready_ids_result.scalars().all())
        if not ready_ids:
            return 0

        ready_rows_query = (
            select(PendingArtifactTable)
            .where(PendingArtifactTable.id.in_(ready_ids))
            .order_by(
                PendingArtifactTable.created_at.asc(), PendingArtifactTable.id.asc()
            )
        )
        ready_rows_result = await self._session.execute(ready_rows_query)
        ready_rows = list(ready_rows_result.scalars().all())
        return await self._promote_pending_rows(ready_rows)

    async def cleanup_stale_pending_with_rows(
        self, *, retention_hours: int = 24
    ) -> list[PendingArtifactRecord]:
        """Delete stale pending artifacts and return deleted rows."""
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        query = (
            select(PendingArtifactTable)
            .where(PendingArtifactTable.created_at < cutoff)
            .order_by(
                PendingArtifactTable.created_at.asc(), PendingArtifactTable.id.asc()
            )
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        if not rows:
            return []

        row_ids = [row.id for row in rows]
        await self._session.execute(
            delete(PendingArtifactTable).where(PendingArtifactTable.id.in_(row_ids))
        )
        return [self._to_pending_record(row) for row in rows]

    async def _promote_pending_rows(
        self, pending_rows: list[PendingArtifactTable]
    ) -> int:
        """Promote rows into artifacts and remove source pending rows atomically."""
        return len(await self._promote_pending_rows_with_artifacts(pending_rows))

    async def _promote_pending_rows_with_artifacts(
        self, pending_rows: list[PendingArtifactTable]
    ) -> list[ArtifactRecord]:
        """Promote rows into artifacts and return created artifact models."""
        if not pending_rows:
            return []

        pending_ids = [row.id for row in pending_rows]
        created: list[ArtifactTable] = []
        for row in pending_rows:
            artifact = ArtifactTable(
                job_id=row.job_id,
                name=row.name,
                type=row.type,
                size_bytes=row.size_bytes,
                content_type=row.content_type,
                sha256=row.sha256,
                storage_backend=row.storage_backend,
                storage_key=row.storage_key,
                status="available",
                error=row.error,
                created_at=row.created_at,
            )
            self._session.add(artifact)
            created.append(artifact)

        await self._session.flush()
        await self._session.execute(
            delete(PendingArtifactTable).where(PendingArtifactTable.id.in_(pending_ids))
        )
        return [self._to_artifact_record(artifact) for artifact in created]

    async def get_by_id(self, artifact_id: str) -> ArtifactRecord | None:
        """Get an artifact by ID."""
        query = select(ArtifactTable).where(ArtifactTable.id == artifact_id)
        result = await self._session.execute(query)
        artifact = result.scalar_one_or_none()
        if artifact is None:
            return None
        return self._to_artifact_record(artifact)

    async def list_by_job(self, job_id: str) -> list[ArtifactRecord]:
        """List all artifacts for a job."""
        query = (
            select(ArtifactTable)
            .where(ArtifactTable.job_id == job_id)
            .order_by(ArtifactTable.created_at.desc())
        )
        result = await self._session.execute(query)
        return [
            self._to_artifact_record(artifact) for artifact in result.scalars().all()
        ]

    async def list_by_job_ids(self, job_ids: list[str]) -> list[ArtifactRecord]:
        """List artifacts for multiple jobs."""
        if not job_ids:
            return []
        query = (
            select(ArtifactTable)
            .where(ArtifactTable.job_id.in_(job_ids))
            .order_by(ArtifactTable.created_at.desc())
        )
        result = await self._session.execute(query)
        return [
            self._to_artifact_record(artifact) for artifact in result.scalars().all()
        ]

    async def delete(self, artifact_id: str) -> bool:
        """Delete an artifact by ID."""
        query = delete(ArtifactTable).where(ArtifactTable.id == artifact_id)
        result = await self._session.execute(query)
        return int(result.rowcount or 0) > 0  # type: ignore
