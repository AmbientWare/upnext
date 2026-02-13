"""Worker API contract payloads."""

from typing import Literal

from pydantic import BaseModel, Field


class WorkerInstance(BaseModel):
    """Worker instance model (registered via Redis heartbeat)."""

    id: str
    worker_name: str
    started_at: str
    last_heartbeat: str
    functions: list[str] = Field(default_factory=list)
    function_names: dict[str, str] = Field(default_factory=dict)
    concurrency: int = 1
    active_jobs: int = 0
    jobs_processed: int = 0
    jobs_failed: int = 0
    hostname: str | None = None


class WorkerInfo(BaseModel):
    """Worker-level aggregate info (grouped by worker name)."""

    name: str
    active: bool = False
    instance_count: int = 0
    instances: list[WorkerInstance] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    function_names: dict[str, str] = Field(default_factory=dict)
    concurrency: int = 0


class WorkersListResponse(BaseModel):
    """Workers list response."""

    workers: list[WorkerInfo]
    total: int


class WorkersSnapshotEvent(BaseModel):
    """Realtime snapshot event for workers list."""

    type: Literal["workers.snapshot"] = "workers.snapshot"
    at: str
    workers: WorkersListResponse


class WorkerStats(BaseModel):
    """Worker statistics."""

    total: int


__all__ = [
    "WorkerInstance",
    "WorkerInfo",
    "WorkersListResponse",
    "WorkersSnapshotEvent",
    "WorkerStats",
]
