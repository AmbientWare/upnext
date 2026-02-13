"""Artifact API contract payloads."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from shared.artifacts import ArtifactType


class ArtifactResponse(BaseModel):
    """Single artifact response."""

    id: str
    job_id: str
    name: str
    type: str
    content_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    storage_backend: str
    storage_key: str
    status: str = "available"
    error: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArtifactListResponse(BaseModel):
    """List of artifacts response."""

    artifacts: list[ArtifactResponse]
    total: int


class CreateArtifactRequest(BaseModel):
    """Request to create an artifact."""

    name: str
    type: ArtifactType
    data: Any = None


class ArtifactQueuedResponse(BaseModel):
    """Artifact accepted but queued until the job row is available."""

    status: Literal["queued"] = "queued"
    job_id: str
    pending_id: str


ArtifactCreateResponse = ArtifactResponse | ArtifactQueuedResponse


class ArtifactDeleteResponse(BaseModel):
    """Artifact deletion response."""

    status: Literal["deleted"] = "deleted"
    id: str


class ArtifactStreamEvent(BaseModel):
    """Realtime artifact lifecycle event for dashboard consumers."""

    type: Literal[
        "artifact.created",
        "artifact.queued",
        "artifact.promoted",
        "artifact.deleted",
    ]
    at: str
    job_id: str
    artifact_id: str | None = None
    pending_id: str | None = None
    artifact: ArtifactResponse | None = None


class ErrorResponse(BaseModel):
    """Standard API error payload."""

    detail: str


__all__ = [
    "ArtifactResponse",
    "ArtifactListResponse",
    "CreateArtifactRequest",
    "ArtifactQueuedResponse",
    "ArtifactCreateResponse",
    "ArtifactDeleteResponse",
    "ArtifactStreamEvent",
    "ErrorResponse",
]
