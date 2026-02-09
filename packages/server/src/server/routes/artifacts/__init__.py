"""Artifact routes."""

from fastapi import APIRouter

from server.db.repository import ArtifactRepository
from server.routes.artifacts.artifacts_root import (
    artifact_root_router,
    delete_artifact,
    get_artifact,
)
from server.routes.artifacts.artifacts_stream import (
    artifact_stream_router,
    stream_job_artifacts,
)
from server.routes.artifacts.artifacts_utils import calculate_artifact_size
from server.routes.artifacts.job_artifacts import (
    create_artifact,
    job_artifacts_router,
    list_artifacts,
)

JOB_ARTIFACTS_PREFIX = "/jobs/{job_id}/artifacts"
ARTIFACTS_PREFIX = "/artifacts"

router = APIRouter(tags=["artifacts"])
router.include_router(job_artifacts_router, prefix=JOB_ARTIFACTS_PREFIX)
router.include_router(artifact_stream_router, prefix=JOB_ARTIFACTS_PREFIX)
router.include_router(artifact_root_router, prefix=ARTIFACTS_PREFIX)

__all__ = [
    "ARTIFACTS_PREFIX",
    "ArtifactRepository",
    "JOB_ARTIFACTS_PREFIX",
    "calculate_artifact_size",
    "artifact_root_router",
    "artifact_stream_router",
    "create_artifact",
    "delete_artifact",
    "get_artifact",
    "job_artifacts_router",
    "list_artifacts",
    "router",
    "stream_job_artifacts",
]
