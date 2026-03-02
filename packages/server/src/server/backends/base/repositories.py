"""Abstract repository contracts shared by all persistence backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime

from pydantic import TypeAdapter

from server.backends.base.models import ApiKey, Job, Secret, User
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
_USER_ADAPTER: TypeAdapter[User] = TypeAdapter(User)
_API_KEY_ADAPTER: TypeAdapter[ApiKey] = TypeAdapter(ApiKey)
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
    async def get_by_id(self, id: str) -> Job | None: ...

    @abstractmethod
    async def list_job_subtree(self, id: str) -> list[Job]: ...

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
    ) -> int: ...

    @abstractmethod
    async def get_stats(
        self,
        function: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> JobStatsSummary: ...

    @abstractmethod
    async def get_durations(
        self,
        *,
        function: str,
        start_date: datetime,
    ) -> list[float]: ...

    @abstractmethod
    async def get_hourly_trends(
        self,
        *,
        start_date: datetime,
        end_date: datetime,
        function: str | None = None,
        functions: list[str] | None = None,
    ) -> list[JobHourlyTrendRow]: ...

    @abstractmethod
    async def get_function_job_stats(
        self,
        *,
        start_date: datetime,
    ) -> dict[str, FunctionJobStats]: ...

    @abstractmethod
    async def get_function_wait_stats(
        self,
        *,
        start_date: datetime,
        function: str | None = None,
    ) -> dict[str, FunctionWaitStats]: ...

    @abstractmethod
    async def list_stuck_active_jobs(
        self,
        *,
        started_before: datetime,
        limit: int = 10,
    ) -> list[Job]: ...

    @abstractmethod
    async def list_old_ids(self, retention_hours: int = 24) -> list[str]: ...

    @abstractmethod
    async def delete_by_ids(self, ids: list[str]) -> int: ...

    @abstractmethod
    async def save_job(self, job: Job) -> None: ...


class BaseArtifactRepository(ABC):
    @staticmethod
    def _to_model_artifact(payload: object) -> ArtifactRecord:
        return _ARTIFACT_ADAPTER.validate_python(payload, from_attributes=True)

    @staticmethod
    def _to_model_pending_artifact(payload: object) -> PendingArtifactRecord:
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
    ) -> PendingArtifactRecord: ...

    @abstractmethod
    async def promote_pending_for_job(self, job_id: str) -> int: ...

    @abstractmethod
    async def promote_pending_for_job_with_artifacts(
        self, job_id: str
    ) -> list[ArtifactRecord]: ...

    @abstractmethod
    async def promote_ready_pending(self, *, limit: int = 500) -> int: ...

    @abstractmethod
    async def cleanup_stale_pending_with_rows(
        self, *, retention_hours: int = 24
    ) -> list[PendingArtifactRecord]: ...

    @abstractmethod
    async def get_by_id(self, artifact_id: str) -> ArtifactRecord | None: ...

    @abstractmethod
    async def list_by_job(self, job_id: str) -> list[ArtifactRecord]: ...

    @abstractmethod
    async def list_by_job_ids(self, job_ids: list[str]) -> list[ArtifactRecord]: ...

    @abstractmethod
    async def delete(self, artifact_id: str) -> bool: ...


class BaseAuthRepository(ABC):
    @staticmethod
    def _to_model_user(payload: object) -> User:
        if isinstance(payload, User):
            return payload
        if not isinstance(payload, Mapping):
            payload = {
                "id": getattr(payload, "id"),
                "username": getattr(payload, "username"),
                "is_admin": getattr(payload, "is_admin"),
                "created_at": getattr(payload, "created_at"),
                "updated_at": getattr(payload, "updated_at"),
            }
        return _USER_ADAPTER.validate_python(payload)

    @staticmethod
    def _to_model_api_key(payload: object) -> ApiKey:
        if isinstance(payload, ApiKey):
            return payload
        if not isinstance(payload, Mapping):
            payload = {
                "id": getattr(payload, "id"),
                "user_id": getattr(payload, "user_id"),
                "key_hash": getattr(payload, "key_hash"),
                "key_prefix": getattr(payload, "key_prefix"),
                "name": getattr(payload, "name"),
                "is_active": getattr(payload, "is_active"),
                "created_at": getattr(payload, "created_at"),
                "updated_at": getattr(payload, "updated_at"),
                "last_used_at": getattr(payload, "last_used_at"),
            }
        return _API_KEY_ADAPTER.validate_python(payload)

    @abstractmethod
    async def get_user_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None: ...

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> User | None: ...

    @abstractmethod
    async def seed_admin_api_key(self, raw_key: str) -> None: ...

    @abstractmethod
    async def list_users(self) -> list[tuple[User, int]]: ...

    @abstractmethod
    async def create_user(self, username: str, is_admin: bool = False) -> User: ...

    @abstractmethod
    async def delete_user(self, user_id: str) -> bool: ...

    @abstractmethod
    async def update_user(
        self, user_id: str, *, is_admin: bool | None = None
    ) -> User | None: ...

    @abstractmethod
    async def list_api_keys_for_user(self, user_id: str) -> list[ApiKey]: ...

    @abstractmethod
    async def create_api_key(
        self, user_id: str, name: str = "default"
    ) -> tuple[ApiKey, str]: ...

    @abstractmethod
    async def delete_api_key(self, key_id: str) -> bool: ...

    @abstractmethod
    async def rotate_api_key(self, user_id: str) -> tuple[ApiKey, str]: ...

    @abstractmethod
    async def toggle_api_key(self, key_id: str, is_active: bool) -> ApiKey | None: ...

    @abstractmethod
    async def save_api_key(self, api_key: ApiKey) -> None: ...


class BaseSecretsRepository(ABC):
    @staticmethod
    def _to_model(payload: object) -> Secret:
        if isinstance(payload, Secret):
            return payload
        if not isinstance(payload, Mapping):
            payload = {
                "id": getattr(payload, "id"),
                "name": getattr(payload, "name"),
                "encrypted_data": getattr(payload, "encrypted_data"),
                "created_at": getattr(payload, "created_at"),
                "updated_at": getattr(payload, "updated_at"),
            }
        return _SECRET_ADAPTER.validate_python(payload)

    @abstractmethod
    async def list_secrets(self) -> list[Secret]: ...

    @abstractmethod
    async def get_secret_by_name(self, name: str) -> Secret | None: ...

    @abstractmethod
    async def get_secret_by_id(self, secret_id: str) -> Secret | None: ...

    @abstractmethod
    async def create_secret(self, name: str, data: dict[str, str]) -> Secret: ...

    @abstractmethod
    async def update_secret(
        self,
        secret_id: str,
        *,
        name: str | None = None,
        data: dict[str, str] | None = None,
    ) -> Secret | None: ...

    @abstractmethod
    async def delete_secret(self, secret_id: str) -> bool: ...

    @abstractmethod
    def decrypt_secret(self, secret: Secret) -> dict[str, str]: ...
