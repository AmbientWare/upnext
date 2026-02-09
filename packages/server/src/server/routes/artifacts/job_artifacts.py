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
    calculate_artifact_size,
    publish_artifact_event,
)

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
    size_bytes = calculate_artifact_size(request.data)

    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db.session() as session:
        job_repo = JobRepository(session)
        repo = ArtifactRepository(session)

        if await job_repo.get_by_id(job_id):
            try:
                artifact = await repo.create(
                    job_id=job_id,
                    name=request.name,
                    artifact_type=request.type,
                    data=request.data,
                    size_bytes=size_bytes,
                )

                logger.debug("Created artifact '%s' for job %s", request.name, job_id)
                response_artifact = ArtifactResponse(
                    id=artifact.id,
                    job_id=artifact.job_id,
                    name=artifact.name,
                    type=artifact.type,
                    size_bytes=artifact.size_bytes,
                    data=artifact.data,
                    path=artifact.path,
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
                    data=request.data,
                    size_bytes=size_bytes,
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
            data=request.data,
            size_bytes=size_bytes,
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
                    size_bytes=a.size_bytes,
                    data=a.data,
                    path=a.path,
                    created_at=a.created_at,
                )
                for a in artifacts
            ],
            total=len(artifacts),
        )
