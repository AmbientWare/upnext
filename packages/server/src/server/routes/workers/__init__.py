"""Workers routes."""

from fastapi import APIRouter
from shared.schemas import WorkerInfo, WorkerInstance, WorkersListResponse

from server.routes.workers.workers_root import (
    get_worker_route,
    list_workers_route,
    worker_root_router,
)
from server.routes.workers.workers_stream import stream_workers, worker_stream_router

WORKERS_PREFIX = "/workers"

router = APIRouter(tags=["workers"])
# Register concrete stream route before dynamic `/{worker_id}` route so
# `/workers/stream` is not captured as a worker id.
router.include_router(worker_stream_router, prefix=WORKERS_PREFIX)
router.include_router(worker_root_router, prefix=WORKERS_PREFIX)

__all__ = [
    "WORKERS_PREFIX",
    "WorkerInfo",
    "WorkerInstance",
    "WorkersListResponse",
    "get_worker_route",
    "list_workers_route",
    "router",
    "stream_workers",
    "worker_root_router",
    "worker_stream_router",
]
