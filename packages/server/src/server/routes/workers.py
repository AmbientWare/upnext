"""Worker registration routes using Redis for state."""

import logging

from fastapi import APIRouter, HTTPException
from server.services import (
    deregister_worker,
    get_function_definitions,
    get_worker,
    heartbeat_worker,
    list_workers,
    register_worker,
)
from shared.events import WorkerDeregisterRequest, WorkerRegisterRequest
from shared.schemas import (
    HeartbeatRequest,
    Worker,
    WorkerResponse,
    WorkersListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workers", tags=["workers"])


@router.post("/register", response_model=WorkerResponse)
async def register_worker_route(request: WorkerRegisterRequest) -> WorkerResponse:
    """
    Register a worker with the API.

    Stores worker data in Redis with TTL. Worker must send heartbeats
    to stay registered.
    """
    # Convert function definitions to dicts
    func_defs = [
        {
            "name": fd.name,
            "type": fd.type,
            "timeout": fd.timeout,
            "max_retries": fd.max_retries,
            "retry_delay": fd.retry_delay,
            "schedule": fd.schedule,
            "timezone": fd.timezone,
            "pattern": fd.pattern,
            "source": fd.source,
            "batch_size": fd.batch_size,
            "batch_timeout": fd.batch_timeout,
            "max_concurrency": fd.max_concurrency,
        }
        for fd in request.function_definitions
    ]

    await register_worker(
        worker_id=request.worker_id,
        worker_name=request.worker_name,
        started_at=request.started_at,
        functions=request.functions,
        concurrency=request.concurrency,
        hostname=request.hostname,
        version=request.version,
        function_definitions=func_defs,
    )

    logger.info(
        f"Worker registered: {request.worker_id} ({request.worker_name}) "
        f"with {len(request.function_definitions)} functions"
    )

    return WorkerResponse(
        worker_id=request.worker_id,
        status="registered",
    )


@router.post("/heartbeat", response_model=WorkerResponse)
async def worker_heartbeat_route(request: HeartbeatRequest) -> WorkerResponse:
    """
    Update worker heartbeat - refreshes TTL.

    Workers should call this every 5 seconds to stay registered.
    """
    success = await heartbeat_worker(
        worker_id=request.worker_id,
        active_jobs=request.active_jobs,
        jobs_processed=request.jobs_processed,
        jobs_failed=request.jobs_failed,
        queued_jobs=request.queued_jobs,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Worker not registered")

    return WorkerResponse(worker_id=request.worker_id, status="ok")


@router.post("/deregister", response_model=WorkerResponse)
async def deregister_worker_route(request: WorkerDeregisterRequest) -> WorkerResponse:
    """
    Deregister a worker from the API.

    Called when a worker shuts down gracefully. Also happens automatically
    when TTL expires if worker crashes.
    """
    await deregister_worker(request.worker_id)

    return WorkerResponse(
        worker_id=request.worker_id,
        status="deregistered",
    )


@router.get("/", response_model=WorkersListResponse)
async def list_workers_route() -> WorkersListResponse:
    """List all active workers."""
    workers = await list_workers()
    return WorkersListResponse(workers=workers, total=len(workers))


@router.get("/{worker_id}", response_model=Worker)
async def get_worker_route(worker_id: str) -> Worker:
    """Get a specific worker by ID."""
    worker = await get_worker(worker_id)

    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    return worker


# Re-export for other routes that need it
__all__ = ["router", "get_function_definitions"]
