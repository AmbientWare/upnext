"""Worker routes - reads worker data from Redis."""

import logging

from fastapi import APIRouter, HTTPException
from shared.schemas import (
    WorkerInfo,
    WorkerInstance,
    WorkersListResponse,
)

from server.services.workers import (
    get_worker_definitions,
    get_worker_instance,
    list_worker_instances,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("", response_model=WorkersListResponse)
async def list_workers_route() -> WorkersListResponse:
    """List all workers with active instances, matching API pattern."""
    try:
        worker_defs = await get_worker_definitions()
        all_instances = await list_worker_instances()
    except RuntimeError:
        return WorkersListResponse(workers=[], total=0)

    # Group instances by worker_name
    instances_by_name: dict[str, list[WorkerInstance]] = {}
    for inst in all_instances:
        instances_by_name.setdefault(inst.worker_name, []).append(inst)

    workers: list[WorkerInfo] = []

    # Build from persistent definitions (always shown, even when inactive)
    for name, defn in worker_defs.items():
        instances = instances_by_name.pop(name, [])
        workers.append(
            WorkerInfo(
                name=name,
                active=bool(instances),
                instance_count=len(instances),
                instances=instances,
                functions=defn.get("functions", []),
                concurrency=defn.get("concurrency", 0),
            )
        )

    # Also include workers with live instances but no persistent definition yet
    for name, instances in instances_by_name.items():
        first = instances[0]
        workers.append(
            WorkerInfo(
                name=name,
                active=True,
                instance_count=len(instances),
                instances=instances,
                functions=first.functions,
                concurrency=first.concurrency,
            )
        )

    return WorkersListResponse(workers=workers, total=len(workers))


@router.get("/{worker_id}", response_model=WorkerInstance)
async def get_worker_route(worker_id: str) -> WorkerInstance:
    """Get a specific worker instance by ID."""
    try:
        instance = await get_worker_instance(worker_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if not instance:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    return instance
