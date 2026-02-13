"""Function registry and function dashboard contract payloads."""

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.common import FunctionType, MissedRunPolicy
from shared.contracts.jobs import Run


class FunctionConfig(BaseModel):
    """Persisted function definition/config written by workers."""

    key: str
    name: str
    type: FunctionType = FunctionType.TASK
    paused: bool = False
    timeout: float | None = None
    max_retries: int | None = None
    retry_delay: float | None = None
    rate_limit: str | None = None
    max_concurrency: int | None = None
    routing_group: str | None = None
    group_max_concurrency: int | None = None
    schedule: str | None = None
    next_run_at: str | None = None
    missed_run_policy: MissedRunPolicy | None = None
    max_catch_up_seconds: float | None = None
    pattern: str | None = None

    model_config = ConfigDict(extra="ignore")


class DispatchReasonMetrics(BaseModel):
    """Per-function dispatch deferral/skip counters."""

    paused: int = 0
    rate_limited: int = 0
    no_capacity: int = 0
    cancelled: int = 0
    retrying: int = 0


class FunctionInfo(BaseModel):
    """Function info."""

    key: str
    name: str
    type: FunctionType
    active: bool = False
    paused: bool = False
    timeout: float | None = None
    max_retries: int | None = None
    retry_delay: float | None = None
    rate_limit: str | None = None
    max_concurrency: int | None = None
    routing_group: str | None = None
    group_max_concurrency: int | None = None
    schedule: str | None = None
    next_run_at: str | None = None
    missed_run_policy: MissedRunPolicy | None = None
    max_catch_up_seconds: float | None = None
    pattern: str | None = None
    workers: list[str] = Field(default_factory=list)
    runs_24h: int = 0
    success_rate: float = 100.0
    avg_duration_ms: float = 0.0
    p95_duration_ms: float | None = None
    avg_wait_ms: float | None = None
    p95_wait_ms: float | None = None
    queue_backlog: int = 0
    dispatch_reasons: DispatchReasonMetrics = Field(
        default_factory=DispatchReasonMetrics
    )
    last_run_at: str | None = None
    last_run_status: str | None = None


class FunctionsListResponse(BaseModel):
    """Functions list response."""

    functions: list[FunctionInfo]
    total: int


class FunctionDetailResponse(FunctionInfo):
    """Function detail response."""

    recent_runs: list[Run] = Field(default_factory=list)


__all__ = [
    "FunctionConfig",
    "DispatchReasonMetrics",
    "FunctionInfo",
    "FunctionsListResponse",
    "FunctionDetailResponse",
]
