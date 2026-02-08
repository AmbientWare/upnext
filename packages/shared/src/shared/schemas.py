"""Shared API schemas for Conduit."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

from shared.artifacts import ArtifactType

# =============================================================================
# Common Types
# =============================================================================


class FunctionType(StrEnum):
    TASK = "task"
    CRON = "cron"
    EVENT = "event"


# =============================================================================
# Job History Schemas
# =============================================================================


class JobHistoryResponse(BaseModel):
    """Single job history response."""

    id: str
    function: str
    function_name: str
    status: str
    created_at: datetime | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempts: int = 1
    max_retries: int = 0
    timeout: float | None = None
    worker_id: str | None = None
    parent_id: str | None = None
    root_id: str
    progress: float = 0.0
    kwargs: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    result: Any = None
    error: str | None = None
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


class JobTrendHour(BaseModel):
    """Hourly job counts by status."""

    hour: str  # ISO format: "2024-01-15T14:00:00Z"
    complete: int = 0
    failed: int = 0
    retrying: int = 0
    active: int = 0


class JobTrendsResponse(BaseModel):
    """Job trends response."""

    hourly: list[JobTrendHour]


# =============================================================================
# Artifact Schemas
# =============================================================================


class ArtifactResponse(BaseModel):
    """Single artifact response."""

    id: int
    job_id: str
    name: str
    type: str  # text, json, image/png, image/jpeg, file/pdf, etc.
    size_bytes: int | None = None
    data: Any = None
    path: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ArtifactListResponse(BaseModel):
    """List of artifacts response."""

    artifacts: list[ArtifactResponse]
    total: int


class CreateArtifactRequest(BaseModel):
    """Request to create an artifact."""

    name: str
    type: ArtifactType
    data: Any = None


class ArtifactQueuedResponse(BaseModel):
    """Artifact accepted but queued until the job row is available."""

    status: Literal["queued"] = "queued"
    job_id: str
    pending_id: int


ArtifactCreateResponse = ArtifactResponse | ArtifactQueuedResponse


class ErrorResponse(BaseModel):
    """Standard API error payload."""

    detail: str


# =============================================================================
# Run/Job Schemas
# =============================================================================


class Run(BaseModel):
    """Run model for job executions."""

    id: str
    function: str
    function_name: str
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


class WorkerInstance(BaseModel):
    """Worker instance model (registered via Redis heartbeat)."""

    id: str
    worker_name: str
    started_at: str
    last_heartbeat: str
    functions: list[str] = []
    function_names: dict[str, str] = {}
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
    instances: list[WorkerInstance] = []
    functions: list[str] = []
    function_names: dict[str, str] = {}
    concurrency: int = 0


class WorkersListResponse(BaseModel):
    """Workers list response."""

    workers: list[WorkerInfo]
    total: int


class WorkerStats(BaseModel):
    """Worker statistics."""

    total: int


# =============================================================================
# API Instance Schemas
# =============================================================================


class ApiInstance(BaseModel):
    """API instance model (registered via Redis heartbeat)."""

    id: str
    api_name: str
    started_at: str
    last_heartbeat: str
    host: str = "0.0.0.0"
    port: int = 8000
    endpoints: list[str] = []
    hostname: str | None = None


HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class ApiEndpoint(BaseModel):
    """API endpoint info."""

    method: HttpMethod
    path: str
    requests_24h: int = 0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    error_rate: float = 0.0
    last_request_at: str | None = None


class ApiInfo(BaseModel):
    """API-level aggregate info (grouped by API name)."""

    name: str
    active: bool = False
    instance_count: int = 0
    instances: list[ApiInstance] = []
    endpoint_count: int = 0
    requests_24h: int = 0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    requests_per_min: float = 0.0


class ApisListResponse(BaseModel):
    """APIs list response."""

    apis: list[ApiInfo]
    total: int


class EndpointsListResponse(BaseModel):
    """Endpoints list response (per-endpoint detail)."""

    endpoints: list[ApiEndpoint]
    total: int


class ApiDetailResponse(ApiEndpoint):
    """API endpoint detail response."""

    hourly_stats: list = []
    recent_errors: list = []


class ApiTrendHour(BaseModel):
    """Hourly API response counts by status category."""

    hour: str
    success_2xx: int = 0
    client_4xx: int = 0
    server_5xx: int = 0


class ApiTrendsResponse(BaseModel):
    """API trends response."""

    hourly: list[ApiTrendHour]


# =============================================================================
# Function Schemas
# =============================================================================


class FunctionInfo(BaseModel):
    """Function info."""

    key: str
    name: str
    type: FunctionType
    active: bool = False
    # Task config
    timeout: int | None = None
    max_retries: int | None = None
    retry_delay: int | None = None
    # Cron config
    schedule: str | None = None
    next_run_at: str | None = None
    # Event config
    pattern: str | None = None
    # Workers currently handling this function
    workers: list[str] = []
    # Stats
    runs_24h: int = 0
    success_rate: float = 100.0
    avg_duration_ms: float = 0.0
    p95_duration_ms: float | None = None
    last_run_at: str | None = None
    last_run_status: str | None = None


class FunctionsListResponse(BaseModel):
    """Functions list response."""

    functions: list[FunctionInfo]
    total: int


class FunctionDetailResponse(FunctionInfo):
    """Function detail response."""

    recent_runs: list[Run] = []


# =============================================================================
# Dashboard Schemas
# =============================================================================


class RunStats(BaseModel):
    """Run statistics."""

    total_24h: int
    success_rate: float
    active_count: int


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
