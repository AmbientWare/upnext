"""Redis-backed artifact repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from pydantic import ValidationError
from redis.asyncio import Redis
from shared.keys import DEFAULT_WORKSPACE_ID

from server.backends.base.repositories import BaseArtifactRepository
from server.backends.base.repository_models import ArtifactRecord, PendingArtifactRecord
from server.backends.base.utils import infer_artifact_metadata
from server.backends.redis.repositories._utils import (
    decode_text,
    dumps,
    loads,
    utcnow,
)
from server.backends.redis.repositories.typing import AsyncRedisClient

_ARTIFACTS_SET = "upnext:persist:artifacts:ids"
_PENDING_SET = "upnext:persist:artifacts:pending:ids"


def _job_key(job_id: str) -> str:
    return f"upnext:persist:jobs:{job_id}"


def _artifact_key(artifact_id: str) -> str:
    return f"upnext:persist:artifacts:{artifact_id}"


def _artifact_job_key(job_id: str) -> str:
    return f"upnext:persist:artifacts:job:{job_id}"


def _pending_key(pending_id: str) -> str:
    return f"upnext:persist:artifacts:pending:{pending_id}"


def _pending_job_key(job_id: str) -> str:
    return f"upnext:persist:artifacts:pending:job:{job_id}"


def _encode_artifact(record: ArtifactRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "job_id": record.job_id,
        "name": record.name,
        "type": record.type,
        "size_bytes": record.size_bytes,
        "content_type": record.content_type,
        "sha256": record.sha256,
        "storage_backend": record.storage_backend,
        "storage_key": record.storage_key,
        "status": record.status,
        "error": record.error,
        "created_at": record.created_at.isoformat(),
    }


def _decode_artifact(payload: dict[str, object]) -> ArtifactRecord | None:
    try:
        return BaseArtifactRepository._to_model_artifact(payload)
    except ValidationError:
        return None


def _encode_pending(record: PendingArtifactRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "job_id": record.job_id,
        "name": record.name,
        "type": record.type,
        "size_bytes": record.size_bytes,
        "content_type": record.content_type,
        "sha256": record.sha256,
        "storage_backend": record.storage_backend,
        "storage_key": record.storage_key,
        "status": record.status,
        "error": record.error,
        "created_at": record.created_at.isoformat(),
    }


def _decode_pending(payload: dict[str, object]) -> PendingArtifactRecord | None:
    try:
        return BaseArtifactRepository._to_model_pending_artifact(payload)
    except ValidationError:
        return None


class RedisArtifactRepository(BaseArtifactRepository):
    def __init__(self, redis: Redis) -> None:
        self._redis: AsyncRedisClient = cast(AsyncRedisClient, redis)

    async def _read_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        payload = loads(await self._redis.get(_artifact_key(artifact_id)))
        return _decode_artifact(payload) if payload else None

    async def _write_artifact(self, record: ArtifactRecord) -> None:
        await self._redis.set(_artifact_key(record.id), dumps(_encode_artifact(record)))
        await self._redis.sadd(_ARTIFACTS_SET, record.id)
        await self._redis.sadd(_artifact_job_key(record.job_id), record.id)

    async def _read_pending(self, pending_id: str) -> PendingArtifactRecord | None:
        payload = loads(await self._redis.get(_pending_key(pending_id)))
        return _decode_pending(payload) if payload else None

    async def _write_pending(self, record: PendingArtifactRecord) -> None:
        await self._redis.set(_pending_key(record.id), dumps(_encode_pending(record)))
        await self._redis.sadd(_PENDING_SET, record.id)
        await self._redis.sadd(_pending_job_key(record.job_id), record.id)

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
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> ArtifactRecord:
        size_bytes, content_type = infer_artifact_metadata(
            data=data,
            path=path,
            size_bytes=size_bytes,
            content_type=content_type,
        )
        record = ArtifactRecord(
            id=str(uuid4()),
            workspace_id=workspace_id,
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
            created_at=utcnow(),
        )
        await self._write_artifact(record)
        return record

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
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> PendingArtifactRecord:
        size_bytes, content_type = infer_artifact_metadata(
            data=data,
            path=path,
            size_bytes=size_bytes,
            content_type=content_type,
        )
        record = PendingArtifactRecord(
            id=str(uuid4()),
            workspace_id=workspace_id,
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
            created_at=utcnow(),
        )
        await self._write_pending(record)
        return record

    async def promote_pending_for_job(
        self, job_id: str, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> int:
        return len(
            await self.promote_pending_for_job_with_artifacts(
                job_id, workspace_id=workspace_id
            )
        )

    async def promote_pending_for_job_with_artifacts(
        self, job_id: str, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[ArtifactRecord]:
        pending_ids = await self._redis.smembers(_pending_job_key(job_id))
        pending_rows: list[PendingArtifactRecord] = []
        for raw_pending_id in pending_ids:
            row = await self._read_pending(decode_text(raw_pending_id))
            if row is not None and row.workspace_id == workspace_id:
                pending_rows.append(row)
        pending_rows.sort(key=lambda row: (row.created_at, row.id))
        return await self._promote_pending_rows(pending_rows)

    async def _promote_pending_rows(
        self, pending_rows: list[PendingArtifactRecord]
    ) -> list[ArtifactRecord]:
        out: list[ArtifactRecord] = []
        for pending in pending_rows:
            artifact = ArtifactRecord(
                id=str(uuid4()),
                workspace_id=pending.workspace_id,
                job_id=pending.job_id,
                name=pending.name,
                type=pending.type,
                size_bytes=pending.size_bytes,
                content_type=pending.content_type,
                sha256=pending.sha256,
                storage_backend=pending.storage_backend,
                storage_key=pending.storage_key,
                status="available",
                error=pending.error,
                created_at=pending.created_at,
            )
            await self._write_artifact(artifact)
            await self._redis.delete(_pending_key(pending.id))
            await self._redis.srem(_PENDING_SET, pending.id)
            await self._redis.srem(_pending_job_key(pending.job_id), pending.id)
            out.append(artifact)
        return out

    async def promote_ready_pending(
        self, *, limit: int = 500, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> int:
        if limit <= 0:
            return 0
        pending_ids = await self._redis.smembers(_PENDING_SET)
        pending_rows: list[PendingArtifactRecord] = []
        for raw_pending_id in pending_ids:
            pending_id = decode_text(raw_pending_id)
            row = await self._read_pending(pending_id)
            if row is None:
                continue
            if row.workspace_id != workspace_id:
                continue
            if await self._redis.exists(_job_key(row.job_id)):
                pending_rows.append(row)
        pending_rows.sort(key=lambda row: (row.created_at, row.id))
        promoted = await self._promote_pending_rows(pending_rows[:limit])
        return len(promoted)

    async def cleanup_stale_pending_with_rows(
        self, *, retention_hours: int = 24, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[PendingArtifactRecord]:
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        pending_ids = await self._redis.smembers(_PENDING_SET)
        stale: list[PendingArtifactRecord] = []
        for raw_pending_id in pending_ids:
            pending_id = decode_text(raw_pending_id)
            row = await self._read_pending(pending_id)
            if row is None:
                continue
            if row.workspace_id != workspace_id:
                continue
            if row.created_at < cutoff:
                stale.append(row)
        stale.sort(key=lambda row: (row.created_at, row.id))
        for row in stale:
            await self._redis.delete(_pending_key(row.id))
            await self._redis.srem(_PENDING_SET, row.id)
            await self._redis.srem(_pending_job_key(row.job_id), row.id)
        return stale

    async def get_by_id(
        self, artifact_id: str, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> ArtifactRecord | None:
        record = await self._read_artifact(artifact_id)
        if record is None or record.workspace_id != workspace_id:
            return None
        return record

    async def list_by_job(
        self, job_id: str, *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[ArtifactRecord]:
        artifact_ids = await self._redis.smembers(_artifact_job_key(job_id))
        out: list[ArtifactRecord] = []
        for raw_artifact_id in artifact_ids:
            record = await self._read_artifact(decode_text(raw_artifact_id))
            if record is not None and record.workspace_id == workspace_id:
                out.append(record)
        out.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        return out

    async def list_by_job_ids(
        self, job_ids: list[str], *, workspace_id: str = DEFAULT_WORKSPACE_ID
    ) -> list[ArtifactRecord]:
        if not job_ids:
            return []
        out: list[ArtifactRecord] = []
        for job_id in job_ids:
            out.extend(await self.list_by_job(job_id, workspace_id=workspace_id))
        out.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        return out

    async def delete(
        self,
        artifact_id: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> bool:
        record = await self.get_by_id(artifact_id, workspace_id=workspace_id)
        if record is None:
            return False
        await self._redis.delete(_artifact_key(artifact_id))
        await self._redis.srem(_ARTIFACTS_SET, artifact_id)
        await self._redis.srem(_artifact_job_key(record.job_id), artifact_id)
        return True
