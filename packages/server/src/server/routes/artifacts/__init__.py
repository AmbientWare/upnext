"""Artifact routes."""

from fastapi import APIRouter

from server.routes.artifacts.artifacts_root import artifact_root_router
from server.routes.artifacts.artifacts_stream import artifact_stream_router

JOB_ARTIFACTS_PREFIX = "/jobs/{job_id}/artifacts"
ARTIFACTS_PREFIX = "/artifacts"

router = APIRouter(tags=["artifacts"])
router.include_router(artifact_stream_router, prefix=JOB_ARTIFACTS_PREFIX)
router.include_router(artifact_root_router, prefix=ARTIFACTS_PREFIX)

__all__ = ["router"]
