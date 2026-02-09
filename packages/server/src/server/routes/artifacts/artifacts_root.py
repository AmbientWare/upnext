"""Global artifact item routes."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from shared.schemas import (
    ArtifactResponse,
    ArtifactStreamEvent,
    ErrorResponse,
)

from server.db.repository import ArtifactRepository
from server.db.session import get_database
from server.routes.artifacts.artifacts_utils import publish_artifact_event

logger = logging.getLogger(__name__)

artifact_root_router = APIRouter(tags=["artifacts"])


@artifact_root_router.get(
    "/{artifact_id}",
    response_model=ArtifactResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Artifact not found."},
        503: {"model": ErrorResponse, "description": "Database not available."},
    },
)
async def get_artifact(artifact_id: int) -> ArtifactResponse:
    """Get an artifact by ID."""
    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db.session() as session:
        repo = ArtifactRepository(session)
        artifact = await repo.get_by_id(artifact_id)

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        return ArtifactResponse(
            id=artifact.id,
            job_id=artifact.job_id,
            name=artifact.name,
            type=artifact.type,
            size_bytes=artifact.size_bytes,
            data=artifact.data,
            path=artifact.path,
            created_at=artifact.created_at,
        )


@artifact_root_router.delete(
    "/{artifact_id}",
    responses={
        404: {"model": ErrorResponse, "description": "Artifact not found."},
        503: {"model": ErrorResponse, "description": "Database not available."},
    },
)
async def delete_artifact(artifact_id: int) -> dict:
    """Delete an artifact."""
    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db.session() as session:
        repo = ArtifactRepository(session)
        artifact = await repo.get_by_id(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        deleted = await repo.delete(artifact_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Artifact not found")

        await publish_artifact_event(
            ArtifactStreamEvent(
                type="artifact.deleted",
                at=datetime.now(UTC).isoformat(),
                job_id=artifact.job_id,
                artifact_id=artifact_id,
                pending_id=None,
                artifact=None,
            )
        )
        return {"status": "deleted", "id": artifact_id}
