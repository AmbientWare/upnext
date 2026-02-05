"""Artifact routes for job outputs."""

import logging

from fastapi import APIRouter, HTTPException
from shared.schemas import (
    ArtifactListResponse,
    ArtifactResponse,
    CreateArtifactRequest,
)

from server.db.repository import ArtifactRepository
from server.db.session import get_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["artifacts"])


@router.post("/jobs/{job_id}/artifacts", response_model=ArtifactResponse)
async def create_artifact(
    job_id: str, request: CreateArtifactRequest
) -> ArtifactResponse:
    """
    Create an artifact for a job.

    Workers call this via ctx.create_artifact() to store outputs
    like text, JSON data, or images.
    """
    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db.session() as session:
        repo = ArtifactRepository(session)

        # Calculate size for text/json data
        size_bytes = None
        if request.data is not None:
            if isinstance(request.data, str):
                size_bytes = len(request.data.encode("utf-8"))
            elif isinstance(request.data, (dict, list)):
                import json

                size_bytes = len(json.dumps(request.data).encode("utf-8"))

        artifact = await repo.create(
            job_id=job_id,
            name=request.name,
            artifact_type=request.type,
            data=request.data,
            size_bytes=size_bytes,
        )

        logger.debug(f"Created artifact '{request.name}' for job {job_id}")

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


@router.get("/jobs/{job_id}/artifacts", response_model=ArtifactListResponse)
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


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
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


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: int) -> dict:
    """Delete an artifact."""
    try:
        db = get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db.session() as session:
        repo = ArtifactRepository(session)
        deleted = await repo.delete(artifact_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Artifact not found")

        return {"status": "deleted", "id": artifact_id}
