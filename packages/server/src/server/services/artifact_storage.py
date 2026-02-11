"""Artifact content storage backends."""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from server.config import get_settings

logger = logging.getLogger(__name__)


def _sanitize_component(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")
    return cleaned or "artifact"


def build_artifact_storage_key(job_id: str, artifact_name: str) -> str:
    safe_name = _sanitize_component(artifact_name)
    return f"jobs/{job_id}/{uuid4().hex}-{safe_name}"


class BaseStorage(ABC):
    """Abstract artifact content storage backend."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short backend identifier persisted with artifact metadata."""

    @abstractmethod
    async def put(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        """Persist bytes to storage."""

    @abstractmethod
    async def get(self, *, key: str) -> bytes:
        """Fetch bytes from storage."""

    @abstractmethod
    async def delete(self, *, key: str) -> None:
        """Delete bytes from storage."""


class LocalStorage(BaseStorage):
    """Store artifacts on local filesystem."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def backend_name(self) -> str:
        return "local"

    def _resolve_key(self, key: str) -> Path:
        target = (self._root / key).resolve()
        if self._root not in target.parents and target != self._root:
            raise ValueError("Invalid storage key path traversal")
        return target

    async def put(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        if content_type:
            logger.debug(
                "Local artifact write key=%s content_type=%s", key, content_type
            )
        target = self._resolve_key(key)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        await asyncio.to_thread(_write)

    async def get(self, *, key: str) -> bytes:
        target = self._resolve_key(key)
        return await asyncio.to_thread(target.read_bytes)

    async def delete(self, *, key: str) -> None:
        target = self._resolve_key(key)

        def _delete() -> None:
            try:
                target.unlink(missing_ok=True)
            except TypeError:
                # Python < 3.8 compatibility fallback (defensive)
                if target.exists():
                    target.unlink()

        await asyncio.to_thread(_delete)


class S3Storage(BaseStorage):
    """Store artifacts in S3-compatible object storage."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._region = region
        self._endpoint_url = endpoint_url

    @property
    def backend_name(self) -> str:
        return "s3"

    def _full_key(self, key: str) -> str:
        if not self._prefix:
            return key
        return f"{self._prefix}/{key}"

    def _client(self):
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError(
                "S3 artifact storage requires boto3. Install boto3 or switch to local storage."
            ) from exc

        return boto3.client(
            "s3",
            region_name=self._region,
            endpoint_url=self._endpoint_url,
        )

    async def put(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        full_key = self._full_key(key)

        def _put() -> None:
            params = {
                "Bucket": self._bucket,
                "Key": full_key,
                "Body": content,
            }
            if content_type:
                params["ContentType"] = content_type
            self._client().put_object(**params)

        await asyncio.to_thread(_put)

    async def get(self, *, key: str) -> bytes:
        full_key = self._full_key(key)

        def _get() -> bytes:
            response = self._client().get_object(Bucket=self._bucket, Key=full_key)
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def delete(self, *, key: str) -> None:
        full_key = self._full_key(key)

        def _delete() -> None:
            self._client().delete_object(Bucket=self._bucket, Key=full_key)

        await asyncio.to_thread(_delete)


def _build_storage_for_backend(backend_name: str) -> BaseStorage:
    """Construct a storage backend instance from app settings."""
    settings = get_settings()
    if backend_name == "s3":
        if not settings.artifact_storage_s3_bucket:
            raise RuntimeError(
                "UPNEXT_ARTIFACT_STORAGE_S3_BUCKET must be set when UPNEXT_ARTIFACT_STORAGE_BACKEND=s3"
            )
        return S3Storage(
            bucket=settings.artifact_storage_s3_bucket,
            prefix=settings.artifact_storage_s3_prefix,
            region=settings.artifact_storage_s3_region,
            endpoint_url=settings.artifact_storage_s3_endpoint_url,
        )

    if backend_name == "local":
        return LocalStorage(settings.artifact_storage_local_root)

    raise RuntimeError(f"Unsupported artifact storage backend: {backend_name}")


@lru_cache
def get_artifact_storage(backend: str | None = None) -> BaseStorage:
    """Return configured artifact storage backend."""
    settings = get_settings()
    resolved_backend = backend or settings.artifact_storage_backend
    return _build_storage_for_backend(resolved_backend)
