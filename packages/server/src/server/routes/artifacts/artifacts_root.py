"""Global artifact item routes."""

import logging
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from shared.schemas import (
    ArtifactResponse,
    ArtifactStreamEvent,
    ErrorResponse,
)

from server.db.repository import ArtifactRepository
from server.db.session import get_database
from server.routes.artifacts.artifacts_utils import publish_artifact_event
from server.services import get_artifact_storage

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
            content_type=artifact.content_type,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            storage_backend=artifact.storage_backend,
            storage_key=artifact.storage_key,
            status=artifact.status,
            error=artifact.error,
            created_at=artifact.created_at,
        )


@artifact_root_router.get(
    "/{artifact_id}/content",
    responses={
        404: {"model": ErrorResponse, "description": "Artifact not found."},
        503: {"model": ErrorResponse, "description": "Storage or database unavailable."},
    },
)
async def get_artifact_content(
    artifact_id: int,
    download: bool = Query(False, description="Force download as attachment"),
) -> Response:
    """Get raw artifact content bytes."""
    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db.session() as session:
        repo = ArtifactRepository(session)
        artifact = await repo.get_by_id(artifact_id)

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

    try:
        storage = get_artifact_storage(artifact.storage_backend)
        content = await storage.get(key=artifact.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Artifact storage unavailable: {exc}") from exc

    headers: dict[str, str] = {}
    if download:
        filename = quote(artifact.name)
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{filename}"

    return Response(
        content=content,
        media_type=artifact.content_type or "application/octet-stream",
        headers=headers,
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

        try:
            storage = get_artifact_storage(artifact.storage_backend)
            await storage.delete(key=artifact.storage_key)
        except Exception:
            # Best effort: still delete DB row.
            pass

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
