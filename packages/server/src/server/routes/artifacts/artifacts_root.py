"""Global artifact item routes."""

import logging
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from shared.contracts import (
    ArtifactCreateResponse,
    ArtifactDeleteResponse,
    ArtifactListResponse,
    ArtifactQueuedResponse,
    ArtifactResponse,
    ArtifactStreamEvent,
    CreateArtifactRequest,
    ErrorResponse,
)
from sqlalchemy.exc import IntegrityError

from server.auth import require_auth_scope
from server.backends.service import BackendService
from server.config import get_settings
from server.routes.artifacts.artifacts_utils import (
    artifact_sha256,
    encode_artifact_payload,
    publish_artifact_event,
)
from server.routes.depends import require_backend
from server.runtime_scope import AuthScope
from server.services.storage import get_artifact_storage

logger = logging.getLogger(__name__)

artifact_root_router = APIRouter(tags=["artifacts"])


@artifact_root_router.post(
    "",
    response_model=ArtifactCreateResponse,
    responses={
        202: {
            "model": ArtifactQueuedResponse,
            "description": "Artifact queued until the job row is available.",
        },
        503: {"model": ErrorResponse, "description": "Backend not available."},
    },
)
async def create_artifact(
    job_id: str,
    request: CreateArtifactRequest,
    response: Response,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
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
    max_bytes = get_settings().artifact_max_upload_bytes
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Artifact too large ({size_bytes} bytes). Max allowed: {max_bytes} bytes.",
        )
    content_hash = artifact_sha256(content)
    storage = get_artifact_storage()
    storage_key = storage.build_artifact_storage_key(job_id, request.name)
    storage_backend = storage.backend_name

    try:
        await storage.put(key=storage_key, content=content, content_type=content_type)
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Artifact storage unavailable: {exc}"
        ) from exc

    async with backend.session() as tx:
        job_repo = tx.jobs
        repo = tx.artifacts

        try:
            if await job_repo.get_by_id(job_id, deployment_id=scope.deployment_id):
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
                        deployment_id=scope.deployment_id,
                    )

                    logger.debug(
                        "Created artifact '%s' for job %s", request.name, job_id
                    )
                    response_artifact = ArtifactResponse.model_validate(artifact)
                    await publish_artifact_event(
                        ArtifactStreamEvent(
                            type="artifact.created",
                            deployment_id=scope.deployment_id,
                            at=datetime.now(UTC).isoformat(),
                            job_id=artifact.job_id,
                            artifact_id=artifact.id,
                            pending_id=None,
                            artifact=response_artifact,
                        )
                    )
                    return response_artifact
                except IntegrityError:
                    await tx.rollback()
                    pending = await repo.create_pending(
                        job_id=job_id,
                        name=request.name,
                        artifact_type=request.type,
                        size_bytes=size_bytes,
                        content_type=content_type,
                        sha256=content_hash,
                        storage_backend=storage_backend,
                        storage_key=storage_key,
                        deployment_id=scope.deployment_id,
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
                            deployment_id=scope.deployment_id,
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
                deployment_id=scope.deployment_id,
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
                    deployment_id=scope.deployment_id,
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


@artifact_root_router.get(
    "",
    response_model=ArtifactListResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Backend not available."},
    },
)
async def list_artifacts(
    job_id: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> ArtifactListResponse:
    """List all artifacts for a job."""
    async with backend.session() as tx:
        repo = tx.artifacts
        artifacts = await repo.list_by_job(job_id, deployment_id=scope.deployment_id)

        return ArtifactListResponse(
            artifacts=[ArtifactResponse.model_validate(a) for a in artifacts],
            total=len(artifacts),
        )


@artifact_root_router.get(
    "/{artifact_id}",
    response_model=ArtifactResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Artifact not found."},
        503: {"model": ErrorResponse, "description": "Backend not available."},
    },
)
async def get_artifact(
    artifact_id: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> ArtifactResponse:
    """Get an artifact by ID."""
    async with backend.session() as tx:
        repo = tx.artifacts
        artifact = await repo.get_by_id(artifact_id, deployment_id=scope.deployment_id)

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        return ArtifactResponse.model_validate(artifact)


@artifact_root_router.get(
    "/{artifact_id}/content",
    responses={
        404: {"model": ErrorResponse, "description": "Artifact not found."},
        503: {
            "model": ErrorResponse,
            "description": "Storage or database unavailable.",
        },
    },
)
async def get_artifact_content(
    artifact_id: str,
    download: bool = Query(False, description="Force download as attachment"),
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> Response:
    """Get raw artifact content bytes."""
    async with backend.session() as tx:
        repo = tx.artifacts
        artifact = await repo.get_by_id(artifact_id, deployment_id=scope.deployment_id)

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

    try:
        storage = get_artifact_storage(artifact.storage_backend)
        content = await storage.get(key=artifact.storage_key)
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Artifact storage unavailable: {exc}"
        ) from exc

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
    response_model=ArtifactDeleteResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Artifact not found."},
        503: {"model": ErrorResponse, "description": "Backend not available."},
    },
)
async def delete_artifact(
    artifact_id: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> ArtifactDeleteResponse:
    """Delete an artifact."""
    async with backend.session() as tx:
        repo = tx.artifacts
        artifact = await repo.get_by_id(artifact_id, deployment_id=scope.deployment_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Artifact not found")

        try:
            storage = get_artifact_storage(artifact.storage_backend)
            await storage.delete(key=artifact.storage_key)
        except Exception:
            # Best effort: still delete DB row.
            pass

        deleted = await repo.delete(artifact_id, deployment_id=scope.deployment_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Artifact not found")

        await publish_artifact_event(
            ArtifactStreamEvent(
                type="artifact.deleted",
                deployment_id=scope.deployment_id,
                at=datetime.now(UTC).isoformat(),
                job_id=artifact.job_id,
                artifact_id=artifact_id,
                pending_id=None,
                artifact=None,
            )
        )
        return ArtifactDeleteResponse(status="deleted", id=artifact_id)
