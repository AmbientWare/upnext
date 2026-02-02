"""Shared API schemas for Conduit."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

# =============================================================================
# Common Types
# =============================================================================

FunctionType = Literal["task", "cron", "event"]


# =============================================================================
# Job History Schemas
# =============================================================================


class JobHistoryResponse(BaseModel):
    """Single job history response."""

    id: str
    key: str
    function: str
    status: str
    created_at: datetime | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempts: int = 1
    max_retries: int = 0
    timeout: float | None = None
    worker_id: str | None = None
    progress: float = 0.0
    kwargs: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    result: Any = None
    error: str | None = None
    state_history: list[dict[str, Any]] = []
    duration_ms: float | None = None

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """List of jobs response."""

    jobs: list[JobHistoryResponse]
    total: int
    has_more: bool = False


class JobStatsResponse(BaseModel):
    """Job statistics response."""

    total: int
    success_count: int
    failure_count: int
    cancelled_count: int
    success_rate: float
    avg_duration_ms: float | None = None


# =============================================================================
# Run/Job Schemas
# =============================================================================


class Run(BaseModel):
    """Run model for job executions."""

    id: str
    function: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float | None = None
    error: str | None = None
    worker_id: str | None = None
    attempts: int = 1
    progress: float = 0.0


# =============================================================================
# Worker Schemas
# =============================================================================


class Worker(BaseModel):
    """Worker model."""

    id: str
    status: str  # 'healthy' | 'unhealthy' | 'stopped'
    started_at: str
    last_heartbeat: str
    functions: list[str]
    concurrency: int
    active_jobs: int
    jobs_processed: int
    jobs_failed: int
    hostname: str | None = None
    version: str | None = None


class WorkerResponse(BaseModel):
    """Worker operation response."""

    worker_id: str
    status: str


class WorkersListResponse(BaseModel):
    """Workers list response."""

    workers: list[Worker]
    total: int


class HeartbeatRequest(BaseModel):
    """Heartbeat request from worker."""

    worker_id: str
    active_jobs: int = 0
    jobs_processed: int = 0
    jobs_failed: int = 0
    # Queue stats (worker reads from Redis and reports)
    queued_jobs: int = 0


class WorkerStats(BaseModel):
    """Worker statistics."""

    total: int
    healthy: int
    unhealthy: int


# =============================================================================
# Function Schemas
# =============================================================================


class FunctionInfo(BaseModel):
    """Function info."""

    name: str
    type: FunctionType
    # Task config
    timeout: int | None = None
    max_retries: int | None = None
    retry_delay: int | None = None
    # Cron config
    schedule: str | None = None
    timezone: str | None = None
    next_run_at: str | None = None
    # Event config
    pattern: str | None = None
    # Stream config
    source: str | None = None
    batch_size: int | None = None
    batch_timeout: float | None = None
    max_concurrency: int | None = None
    # Stats
    runs_24h: int = 0
    success_rate: float = 100.0
    avg_duration_ms: float = 0.0
    p95_duration_ms: float | None = None
    last_run_at: str | None = None
    last_run_status: str | None = None
    # Stream-specific stats
    events_processed_24h: int | None = None
    batches_24h: int | None = None


class FunctionsListResponse(BaseModel):
    """Functions list response."""

    functions: list[FunctionInfo]
    total: int


class HourlyStat(BaseModel):
    """Hourly stat for function detail."""

    hour: str
    success: int
    failure: int


class FunctionDetailResponse(FunctionInfo):
    """Function detail response."""

    recent_runs: list[Run] = []
    hourly_stats: list[HourlyStat] = []


# =============================================================================
# Dashboard Schemas
# =============================================================================


class RunStats(BaseModel):
    """Run statistics."""

    total_24h: int
    success_rate: float
    active_count: int
    queued_count: int


class ApiStats(BaseModel):
    """API statistics."""

    requests_24h: int
    avg_latency_ms: float
    error_rate: float


class DashboardStats(BaseModel):
    """Dashboard stats response."""

    runs: RunStats
    workers: WorkerStats
    apis: ApiStats
    recent_runs: list[Run]
    recent_failures: list[Run]
