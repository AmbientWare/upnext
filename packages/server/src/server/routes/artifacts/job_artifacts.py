"""Job-scoped artifact collection routes."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from shared.schemas import (
    ArtifactCreateResponse,
    ArtifactListResponse,
    ArtifactQueuedResponse,
    ArtifactResponse,
    ArtifactStreamEvent,
    CreateArtifactRequest,
    ErrorResponse,
)
from sqlalchemy.exc import IntegrityError

from server.db.repository import ArtifactRepository, JobRepository
from server.db.session import get_database
from server.routes.artifacts.artifacts_utils import (
    artifact_sha256,
    encode_artifact_payload,
    publish_artifact_event,
)
from server.services import build_artifact_storage_key, get_artifact_storage

logger = logging.getLogger(__name__)

job_artifacts_router = APIRouter(tags=["artifacts"])


@job_artifacts_router.post(
    "",
    response_model=ArtifactCreateResponse,
    responses={
        202: {
            "model": ArtifactQueuedResponse,
            "description": "Artifact queued until the job row is available.",
        },
        503: {"model": ErrorResponse, "description": "Database not available."},
    },
)
async def create_artifact(
    job_id: str, request: CreateArtifactRequest, response: Response
) -> ArtifactCreateResponse:
    """Create an artifact for a specific job."""
    try:
        content, content_type = encode_artifact_payload(
            artifact_type=request.type,
            data=request.data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    size_bytes = len(content)
    content_hash = artifact_sha256(content)
    storage = get_artifact_storage()
    storage_key = build_artifact_storage_key(job_id, request.name)
    storage_backend = storage.backend_name

    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        await storage.put(key=storage_key, content=content, content_type=content_type)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Artifact storage unavailable: {exc}") from exc

    async with db.session() as session:
        job_repo = JobRepository(session)
        repo = ArtifactRepository(session)

        try:
            if await job_repo.get_by_id(job_id):
                try:
                    artifact = await repo.create(
                        job_id=job_id,
                        name=request.name,
                        artifact_type=request.type,
                        size_bytes=size_bytes,
                        content_type=content_type,
                        sha256=content_hash,
                        storage_backend=storage_backend,
                        storage_key=storage_key,
                        status="available",
                    )

                    logger.debug("Created artifact '%s' for job %s", request.name, job_id)
                    response_artifact = ArtifactResponse(
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
                    await publish_artifact_event(
                        ArtifactStreamEvent(
                            type="artifact.created",
                            at=datetime.now(UTC).isoformat(),
                            job_id=artifact.job_id,
                            artifact_id=artifact.id,
                            pending_id=None,
                            artifact=response_artifact,
                        )
                    )
                    return response_artifact
                except IntegrityError:
                    await session.rollback()
                    pending = await repo.create_pending(
                        job_id=job_id,
                        name=request.name,
                        artifact_type=request.type,
                        size_bytes=size_bytes,
                        content_type=content_type,
                        sha256=content_hash,
                        storage_backend=storage_backend,
                        storage_key=storage_key,
                    )
                    logger.debug(
                        "Queued artifact '%s' after insert race for job %s (pending_id=%s)",
                        request.name,
                        job_id,
                        pending.id,
                    )
                    response.status_code = 202
                    queued_response = ArtifactQueuedResponse(
                        status="queued",
                        job_id=job_id,
                        pending_id=pending.id,
                    )
                    await publish_artifact_event(
                        ArtifactStreamEvent(
                            type="artifact.queued",
                            at=datetime.now(UTC).isoformat(),
                            job_id=job_id,
                            artifact_id=None,
                            pending_id=pending.id,
                            artifact=None,
                        )
                    )
                    return queued_response

            pending = await repo.create_pending(
                job_id=job_id,
                name=request.name,
                artifact_type=request.type,
                size_bytes=size_bytes,
                content_type=content_type,
                sha256=content_hash,
                storage_backend=storage_backend,
                storage_key=storage_key,
            )
            logger.debug(
                "Queued artifact '%s' for job %s (pending_id=%s)",
                request.name,
                job_id,
                pending.id,
            )
            response.status_code = 202

            queued_response = ArtifactQueuedResponse(
                status="queued",
                job_id=job_id,
                pending_id=pending.id,
            )
            await publish_artifact_event(
                ArtifactStreamEvent(
                    type="artifact.queued",
                    at=datetime.now(UTC).isoformat(),
                    job_id=job_id,
                    artifact_id=None,
                    pending_id=pending.id,
                    artifact=None,
                )
            )
            return queued_response
        except Exception:
            # Best effort rollback of stored bytes when metadata persistence fails.
            await storage.delete(key=storage_key)
            raise


@job_artifacts_router.get("", response_model=ArtifactListResponse)
async def list_artifacts(job_id: str) -> ArtifactListResponse:
    """List all artifacts for a job."""
    try:
        db = get_database()
    except RuntimeError:
        return ArtifactListResponse(artifacts=[], total=0)

    async with db.session() as session:
        repo = ArtifactRepository(session)
        artifacts = await repo.list_by_job(job_id)

        return ArtifactListResponse(
            artifacts=[
                ArtifactResponse(
                    id=a.id,
                    job_id=a.job_id,
                    name=a.name,
                    type=a.type,
                    content_type=a.content_type,
                    size_bytes=a.size_bytes,
                    sha256=a.sha256,
                    storage_backend=a.storage_backend,
                    storage_key=a.storage_key,
                    status=a.status,
                    error=a.error,
                    created_at=a.created_at,
                )
                for a in artifacts
            ],
            total=len(artifacts),
        )
