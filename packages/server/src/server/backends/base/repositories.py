"""Abstract repository contracts shared by all persistence backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime

from pydantic import TypeAdapter
from shared.keys import DEFAULT_DEPLOYMENT_ID

from server.backends.base.models import Job, Secret
from server.backends.base.repository_models import (
    ArtifactRecord,
    FunctionJobStats,
    FunctionWaitStats,
    JobHourlyTrendRow,
    JobRecordCreate,
    JobStatsSummary,
    PendingArtifactRecord,
)

_JOB_ADAPTER: TypeAdapter[Job] = TypeAdapter(Job)
_SECRET_ADAPTER: TypeAdapter[Secret] = TypeAdapter(Secret)
_ARTIFACT_ADAPTER: TypeAdapter[ArtifactRecord] = TypeAdapter(ArtifactRecord)
_PENDING_ARTIFACT_ADAPTER: TypeAdapter[PendingArtifactRecord] = TypeAdapter(
    PendingArtifactRecord
)


class BaseJobRepository(ABC):
    @staticmethod
    def _to_model(payload: object) -> Job:
        return _JOB_ADAPTER.validate_python(payload, from_attributes=True)

    @abstractmethod
    async def record_job(self, data: JobRecordCreate | Mapping[str, object]) -> Job: ...

    @abstractmethod
    async def get_by_id(
        self, id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> Job | None: ...

    @abstractmethod
    async def list_job_subtree(
        self, id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[Job]: ...

    @abstractmethod
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
    ) -> list[Job]: ...

    @abstractmethod
    async def count_jobs(
        self,
        *,
        function: str | None = None,
        status: str | list[str] | None = None,
        worker_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> int: ...

    @abstractmethod
    async def get_stats(
        self,
        function: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> JobStatsSummary: ...

    @abstractmethod
    async def get_durations(
        self,
        *,
        function: str,
        start_date: datetime,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[float]: ...

    @abstractmethod
    async def get_hourly_trends(
        self,
        *,
        start_date: datetime,
        end_date: datetime,
        function: str | None = None,
        functions: list[str] | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[JobHourlyTrendRow]: ...

    @abstractmethod
    async def get_function_job_stats(
        self,
        *,
        start_date: datetime,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> dict[str, FunctionJobStats]: ...

    @abstractmethod
    async def get_function_wait_stats(
        self,
        *,
        start_date: datetime,
        function: str | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> dict[str, FunctionWaitStats]: ...

    @abstractmethod
    async def list_stuck_active_jobs(
        self,
        *,
        started_before: datetime,
        limit: int = 10,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[Job]: ...

    @abstractmethod
    async def list_old_ids(
        self, retention_hours: int = 24, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[str]: ...

    @abstractmethod
    async def delete_by_ids(
        self, ids: list[str], *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> int: ...

    @abstractmethod
    async def save_job(self, job: Job) -> None: ...


class BaseArtifactRepository(ABC):
    @staticmethod
    def _to_model_artifact(payload: object) -> ArtifactRecord:
        if not isinstance(payload, Mapping):
            payload = {
                "id": getattr(payload, "id"),
                "deployment_id": getattr(payload, "deployment_id"),
                "job_id": getattr(payload, "job_id"),
                "name": getattr(payload, "name"),
                "type": getattr(payload, "type"),
                "size_bytes": getattr(payload, "size_bytes"),
                "content_type": getattr(payload, "content_type"),
                "sha256": getattr(payload, "sha256"),
                "storage_backend": getattr(payload, "storage_backend"),
                "storage_key": getattr(payload, "storage_key"),
                "status": getattr(payload, "status"),
                "error": getattr(payload, "error"),
                "created_at": getattr(payload, "created_at"),
            }
        return _ARTIFACT_ADAPTER.validate_python(payload, from_attributes=True)

    @staticmethod
    def _to_model_pending_artifact(payload: object) -> PendingArtifactRecord:
        if not isinstance(payload, Mapping):
            payload = {
                "id": getattr(payload, "id"),
                "deployment_id": getattr(payload, "deployment_id"),
                "job_id": getattr(payload, "job_id"),
                "name": getattr(payload, "name"),
                "type": getattr(payload, "type"),
                "size_bytes": getattr(payload, "size_bytes"),
                "content_type": getattr(payload, "content_type"),
                "sha256": getattr(payload, "sha256"),
                "storage_backend": getattr(payload, "storage_backend"),
                "storage_key": getattr(payload, "storage_key"),
                "status": getattr(payload, "status"),
                "error": getattr(payload, "error"),
                "created_at": getattr(payload, "created_at"),
            }
        return _PENDING_ARTIFACT_ADAPTER.validate_python(payload, from_attributes=True)

    @abstractmethod
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
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> ArtifactRecord: ...

    @abstractmethod
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
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> PendingArtifactRecord: ...

    @abstractmethod
    async def promote_pending_for_job(
        self, job_id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> int: ...

    @abstractmethod
    async def promote_pending_for_job_with_artifacts(
        self, job_id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[ArtifactRecord]: ...

    @abstractmethod
    async def promote_ready_pending(
        self, *, limit: int = 500, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> int: ...

    @abstractmethod
    async def cleanup_stale_pending_with_rows(
        self, *, retention_hours: int = 24, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[PendingArtifactRecord]: ...

    @abstractmethod
    async def get_by_id(
        self, artifact_id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> ArtifactRecord | None: ...

    @abstractmethod
    async def list_by_job(
        self, job_id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[ArtifactRecord]: ...

    @abstractmethod
    async def list_by_job_ids(
        self, job_ids: list[str], *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> list[ArtifactRecord]: ...

    @abstractmethod
    async def delete(
        self, artifact_id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> bool: ...


class BaseSecretsRepository(ABC):
    @staticmethod
    def _to_model(payload: object) -> Secret:
        if isinstance(payload, Secret):
            return payload
        if not isinstance(payload, Mapping):
            payload = {
                "id": getattr(payload, "id"),
                "deployment_id": getattr(payload, "deployment_id"),
                "name": getattr(payload, "name"),
                "encrypted_data": getattr(payload, "encrypted_data"),
                "created_at": getattr(payload, "created_at"),
                "updated_at": getattr(payload, "updated_at"),
            }
        return _SECRET_ADAPTER.validate_python(payload)

    @abstractmethod
    async def list_secrets(
        self,
        *,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> list[Secret]: ...

    @abstractmethod
    async def get_secret_by_name(
        self, name: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> Secret | None: ...

    @abstractmethod
    async def get_secret_by_id(
        self, secret_id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> Secret | None: ...

    @abstractmethod
    async def create_secret(
        self,
        name: str,
        data: dict[str, str],
        *,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> Secret: ...

    @abstractmethod
    async def update_secret(
        self,
        secret_id: str,
        *,
        name: str | None = None,
        data: dict[str, str] | None = None,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
    ) -> Secret | None: ...

    @abstractmethod
    async def delete_secret(
        self, secret_id: str, *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
    ) -> bool: ...

    @abstractmethod
    def decrypt_secret(self, secret: Secret) -> dict[str, str]: ...
