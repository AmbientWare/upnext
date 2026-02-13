"""Jobs routes."""

from fastapi import APIRouter

from server.routes.jobs.jobs_root import (
    cancel_job_route,
    get_job,
    get_job_stats,
    get_job_timeline,
    get_job_trends,
    list_jobs,
    retry_job,
    router as jobs_root_router,
)
from server.routes.jobs.jobs_stream import jobs_stream_router, stream_job_trends

JOBS_PREFIX = "/jobs"

router = APIRouter(tags=["jobs"])
router.include_router(jobs_root_router, prefix=JOBS_PREFIX)
router.include_router(jobs_stream_router, prefix=JOBS_PREFIX)

cancel_job = cancel_job_route

__all__ = [
    "cancel_job",
    "get_job",
    "get_job_stats",
    "get_job_timeline",
    "get_job_trends",
    "list_jobs",
    "retry_job",
    "router",
    "stream_job_trends",
]
