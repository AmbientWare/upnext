"""Dashboard aggregate contract payloads."""

from pydantic import BaseModel, Field

from shared.contracts.jobs import Run
from shared.contracts.workers import WorkerStats


class RunStats(BaseModel):
    """Run statistics."""

    total_24h: int
    success_rate: float


class QueueStats(BaseModel):
    """Queue depth statistics."""

    running: int
    waiting: int
    claimed: int
    capacity: int
    total: int


class ApiStats(BaseModel):
    """API statistics."""

    requests_24h: int
    avg_latency_ms: float
    error_rate: float


class TopFailingFunction(BaseModel):
    """Runbook row for top failing functions."""

    key: str
    name: str
    runs_24h: int
    failures_24h: int
    failure_rate: float
    last_run_at: str | None = None


class OldestQueuedJob(BaseModel):
    """Runbook row for oldest queued jobs from Redis queues."""

    id: str
    function: str
    function_name: str
    queued_at: str
    age_seconds: float
    source: str


class StuckActiveJob(BaseModel):
    """Runbook row for active jobs exceeding stuck threshold."""

    id: str
    function: str
    function_name: str
    worker_id: str | None = None
    started_at: str
    age_seconds: float


class DashboardStats(BaseModel):
    """Dashboard stats response."""

    runs: RunStats
    queue: QueueStats
    workers: WorkerStats
    apis: ApiStats
    recent_runs: list[Run]
    recent_failures: list[Run]
    top_failing_functions: list[TopFailingFunction] = Field(default_factory=list)
    oldest_queued_jobs: list[OldestQueuedJob] = Field(default_factory=list)
    stuck_active_jobs: list[StuckActiveJob] = Field(default_factory=list)


__all__ = [
    "RunStats",
    "QueueStats",
    "ApiStats",
    "TopFailingFunction",
    "OldestQueuedJob",
    "StuckActiveJob",
    "DashboardStats",
]
