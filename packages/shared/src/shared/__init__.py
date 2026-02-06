"""Shared models for Conduit packages."""

from shared.api import API_PREFIX, HOURLY_BUCKET_TTL, MINUTE_BUCKET_TTL, REGISTRY_TTL
from shared.artifacts import ArtifactType
from shared.events import (
    BatchEventItem,
    BatchEventRequest,
    EventRequest,
    EventType,
    FunctionDefinition,
    HealthResponse,
    JobCheckpointEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobRetryingEvent,
    JobStartedEvent,
    WorkerDeregisterRequest,
    WorkerRegisterRequest,
)
from shared.models import Job, JobStatus, StateTransition
from shared.patterns import get_matching_patterns, matches_event_pattern
from shared.schemas import (
    ApiStats,
    ArtifactListResponse,
    ArtifactResponse,
    CreateArtifactRequest,
    DashboardStats,
    FunctionDetailResponse,
    FunctionInfo,
    FunctionsListResponse,
    FunctionType,
    HeartbeatRequest,
    HourlyStat,
    JobHistoryResponse,
    JobListResponse,
    JobStatsResponse,
    Run,
    RunStats,
    Worker,
    WorkerResponse,
    WorkersListResponse,
    WorkerStats,
)

__all__ = [
    # API tracking constants
    "API_PREFIX",
    "MINUTE_BUCKET_TTL",
    "HOURLY_BUCKET_TTL",
    "REGISTRY_TTL",
    # Core models
    "Job",
    "JobStatus",
    "StateTransition",
    # Events
    "EventType",
    "EventRequest",
    "BatchEventItem",
    "BatchEventRequest",
    "JobStartedEvent",
    "JobCompletedEvent",
    "JobFailedEvent",
    "JobRetryingEvent",
    "JobProgressEvent",
    "JobCheckpointEvent",
    # Artifacts
    "ArtifactType",
    "ArtifactResponse",
    "ArtifactListResponse",
    "CreateArtifactRequest",
    # Worker events
    "WorkerRegisterRequest",
    "WorkerDeregisterRequest",
    "FunctionDefinition",
    # Health
    "HealthResponse",
    # Pattern matching
    "matches_event_pattern",
    "get_matching_patterns",
    # API Schemas
    "FunctionType",
    "Run",
    "Worker",
    "WorkerResponse",
    "WorkersListResponse",
    "HeartbeatRequest",
    "WorkerStats",
    "FunctionInfo",
    "FunctionsListResponse",
    "HourlyStat",
    "FunctionDetailResponse",
    "RunStats",
    "ApiStats",
    "DashboardStats",
    # Job History
    "JobHistoryResponse",
    "JobListResponse",
    "JobStatsResponse",
]
