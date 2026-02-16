"""Core data models for UpNext."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal


@dataclass
class StateTransition:
    """
    Records a state transition for a job.

    Used to build timeline views showing job progression.
    """

    state: str  # JobStatus value
    timestamp: datetime
    message: str | None = None
    worker_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "state": self.state,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "worker_id": self.worker_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateTransition:
        """Deserialize from dictionary."""
        return cls(
            state=data["state"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            message=data.get("message"),
            worker_id=data.get("worker_id"),
        )


class FailureReason(StrEnum):
    """Structured reason for job failure."""

    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class JobStatus(StrEnum):
    """Job execution status."""

    PENDING = "pending"
    QUEUED = "queued"
    ACTIVE = "active"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED)

    def can_transition_to(self, target: JobStatus) -> bool:
        """Check if transition to target state is valid."""
        valid_transitions: dict[JobStatus, set[JobStatus]] = {
            JobStatus.PENDING: {JobStatus.QUEUED, JobStatus.CANCELLED},
            JobStatus.QUEUED: {JobStatus.ACTIVE, JobStatus.CANCELLED},
            JobStatus.ACTIVE: {
                JobStatus.COMPLETE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.RETRYING,
            },
            JobStatus.RETRYING: {
                JobStatus.QUEUED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            },
            JobStatus.COMPLETE: set(),
            JobStatus.FAILED: {JobStatus.QUEUED},  # Allow retry
            JobStatus.CANCELLED: set(),
        }
        return target in valid_transitions.get(self, set())


class JobType(StrEnum):
    """Job source classification."""

    TASK = "task"
    CRON = "cron"
    EVENT = "event"


@dataclass
class TaskSource:
    """Source context for ad-hoc task jobs."""

    type: Literal[JobType.TASK] = JobType.TASK


@dataclass
class CronSource:
    """Source context for recurring cron jobs."""

    schedule: str
    cron_window_at: float | None = None
    startup_reconciled: bool = False
    startup_policy: str | None = None
    type: Literal[JobType.CRON] = JobType.CRON


@dataclass
class EventSource:
    """Source context for event-triggered jobs."""

    event_pattern: str
    event_handler_name: str
    type: Literal[JobType.EVENT] = JobType.EVENT


JobSource = TaskSource | CronSource | EventSource


def clone_job_source(source: JobSource) -> JobSource:
    """Return a detached copy of a job source context."""
    if isinstance(source, CronSource):
        return CronSource(
            schedule=source.schedule,
            cron_window_at=source.cron_window_at,
            startup_reconciled=source.startup_reconciled,
            startup_policy=source.startup_policy,
        )
    if isinstance(source, EventSource):
        return EventSource(
            event_pattern=source.event_pattern,
            event_handler_name=source.event_handler_name,
        )
    return TaskSource()


def _source_to_dict(source: JobSource) -> dict[str, Any]:
    """Serialize typed source context."""
    if isinstance(source, TaskSource):
        return {"type": JobType.TASK.value}
    if isinstance(source, CronSource):
        return {
            "type": JobType.CRON.value,
            "schedule": source.schedule,
            "cron_window_at": source.cron_window_at,
            "startup_reconciled": source.startup_reconciled,
            "startup_policy": source.startup_policy,
        }
    return {
        "type": JobType.EVENT.value,
        "event_pattern": source.event_pattern,
        "event_handler_name": source.event_handler_name,
    }


def _source_from_dict(data: dict[str, Any]) -> JobSource:
    """Deserialize typed source context from persisted job payload."""
    source_raw = data.get("source")
    source_data = source_raw if isinstance(source_raw, dict) else data
    raw_type = source_data.get("type") or data.get("job_type")

    try:
        source_type = JobType(str(raw_type))
    except (TypeError, ValueError):
        source_type = None

    if source_type == JobType.CRON:
        schedule = source_data.get("schedule") or data.get("schedule")
        if isinstance(schedule, str) and schedule:
            return CronSource(
                schedule=schedule,
                cron_window_at=source_data.get(
                    "cron_window_at", data.get("cron_window_at")
                ),
                startup_reconciled=bool(
                    source_data.get(
                        "startup_reconciled", data.get("startup_reconciled", False)
                    )
                ),
                startup_policy=source_data.get(
                    "startup_policy", data.get("startup_policy")
                ),
            )

    if source_type == JobType.EVENT:
        event_pattern = source_data.get("event_pattern") or data.get("event_pattern")
        handler_name = source_data.get("event_handler_name") or data.get(
            "event_handler_name"
        )
        if isinstance(event_pattern, str) and isinstance(handler_name, str):
            return EventSource(
                event_pattern=event_pattern,
                event_handler_name=handler_name,
            )

    # Backward-compatible inference for legacy payloads.
    schedule = data.get("schedule")
    if isinstance(schedule, str) and schedule:
        return CronSource(
            schedule=schedule,
            cron_window_at=data.get("cron_window_at"),
            startup_reconciled=bool(data.get("startup_reconciled", False)),
            startup_policy=data.get("startup_policy"),
        )

    event_pattern = data.get("event_pattern")
    handler_name = data.get("event_handler_name")
    if isinstance(event_pattern, str) and isinstance(handler_name, str):
        return EventSource(
            event_pattern=event_pattern,
            event_handler_name=handler_name,
        )

    return TaskSource()


def _generate_job_id() -> str:
    """Generate a unique job ID."""
    return f"job_{uuid.uuid4().hex[:16]}"


def _utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(UTC)


@dataclass
class Job:
    """
    Represents a job to be executed.

    Jobs are the fundamental unit of work in UpNext.
    """

    # Identity
    function: str
    function_name: str = ""
    kwargs: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=_generate_job_id)
    key: str = ""  # Deduplication key (defaults to id if not set)

    # Status
    status: JobStatus = JobStatus.PENDING

    # Timing
    scheduled_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timeout: float | None = None
    lease_time: float | None = None

    # Execution
    # `attempts` is the number of times the job has been started (1-indexed when running).
    # - 0 = not yet started
    # - 1 = first attempt (initial execution)
    # - 2 = second attempt (first retry)
    # - N = Nth attempt (N-1 retries)
    # Job can retry when: attempts <= max_retries + 1
    # See also: can_retry() method
    attempts: int = 0
    max_retries: int = (
        0  # Number of retry attempts (0 = no retries, just the initial attempt)
    )
    retry_delay: float = 1.0  # Base delay in seconds between retries
    retry_backoff: float = 2.0  # Exponential backoff multiplier
    worker_id: str | None = None
    parent_id: str | None = None
    root_id: str = ""

    # Progress tracking
    progress: float = 0.0
    source: JobSource = field(default_factory=TaskSource)

    # Explicit system/runtime fields (metadata dict removed).
    checkpoint: dict[str, Any] | None = None
    checkpoint_at: str | None = None
    dlq_replayed_from: str | None = None
    dlq_failed_at: str | None = None

    # Result
    result: Any = None
    error: str | None = None
    error_traceback: str | None = None
    failure_reason: FailureReason | None = None

    # State history
    state_history: list[StateTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Set defaults after initialization."""
        if not self.key:
            self.key = self.id
        if not self.root_id:
            self.root_id = self.id
        if not self.function_name:
            self.function_name = self.function

    @property
    def job_type(self) -> JobType:
        """Discriminator describing how the job was created."""
        return self.source.type

    @property
    def source_data(self) -> dict[str, Any]:
        """Serializable view of source context for events/API payloads."""
        return _source_to_dict(self.source)

    @property
    def schedule(self) -> str | None:
        if isinstance(self.source, CronSource):
            return self.source.schedule
        return None

    @property
    def cron_window_at(self) -> float | None:
        if isinstance(self.source, CronSource):
            return self.source.cron_window_at
        return None

    @cron_window_at.setter
    def cron_window_at(self, value: float | None) -> None:
        if isinstance(self.source, CronSource):
            self.source.cron_window_at = value

    @property
    def startup_reconciled(self) -> bool:
        if isinstance(self.source, CronSource):
            return self.source.startup_reconciled
        return False

    @property
    def startup_policy(self) -> str | None:
        if isinstance(self.source, CronSource):
            return self.source.startup_policy
        return None

    @property
    def event_pattern(self) -> str | None:
        if isinstance(self.source, EventSource):
            return self.source.event_pattern
        return None

    @property
    def event_handler_name(self) -> str | None:
        if isinstance(self.source, EventSource):
            return self.source.event_handler_name
        return None

    def _record_transition(
        self,
        state: JobStatus,
        message: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        """Record a state transition to history."""
        self.state_history.append(
            StateTransition(
                state=state.value,
                timestamp=_utc_now(),
                message=message,
                worker_id=worker_id,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize job to dictionary."""
        source_data = self.source_data
        return {
            "id": self.id,
            "key": self.key,
            "function": self.function,
            "function_name": self.function_name,
            "job_type": self.job_type.value,
            "source": source_data,
            "kwargs": self.kwargs,
            "status": self.status.value,
            "scheduled_at": self.scheduled_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "timeout": self.timeout,
            "lease_time": self.lease_time,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "retry_backoff": self.retry_backoff,
            "worker_id": self.worker_id,
            "parent_id": self.parent_id,
            "root_id": self.root_id,
            "progress": self.progress,
            "schedule": self.schedule,
            "cron_window_at": source_data.get("cron_window_at"),
            "startup_reconciled": source_data.get("startup_reconciled", False),
            "startup_policy": source_data.get("startup_policy"),
            "checkpoint": self.checkpoint,
            "checkpoint_at": self.checkpoint_at,
            "dlq_replayed_from": self.dlq_replayed_from,
            "dlq_failed_at": self.dlq_failed_at,
            "event_pattern": source_data.get("event_pattern"),
            "event_handler_name": source_data.get("event_handler_name"),
            "result": self.result,
            "error": self.error,
            "error_traceback": self.error_traceback,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "state_history": [t.to_dict() for t in self.state_history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        """Deserialize job from dictionary."""
        return cls(
            id=data["id"],
            key=data["key"],
            function=data["function"],
            function_name=data.get("function_name", data["function"]),
            kwargs=data.get("kwargs", {}),
            status=JobStatus(data["status"]),
            scheduled_at=datetime.fromisoformat(data["scheduled_at"]),
            started_at=(
                datetime.fromisoformat(data["started_at"])
                if data.get("started_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            timeout=data.get("timeout"),
            lease_time=data.get("lease_time"),
            attempts=data.get("attempts", 0),
            max_retries=data.get("max_retries", 0),
            retry_delay=data.get("retry_delay", 1.0),
            retry_backoff=data.get("retry_backoff", 2.0),
            worker_id=data.get("worker_id"),
            parent_id=data.get("parent_id"),
            root_id=data.get("root_id", data["id"]),
            progress=data.get("progress", 0.0),
            source=_source_from_dict(data),
            checkpoint=data.get("checkpoint"),
            checkpoint_at=data.get("checkpoint_at"),
            dlq_replayed_from=data.get("dlq_replayed_from"),
            dlq_failed_at=data.get("dlq_failed_at"),
            result=data.get("result"),
            error=data.get("error"),
            error_traceback=data.get("error_traceback"),
            failure_reason=FailureReason(data["failure_reason"]) if data.get("failure_reason") else None,
            state_history=[
                StateTransition.from_dict(t) for t in data.get("state_history", [])
            ],
        )

    def to_json(self) -> str:
        """Serialize job to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> Job:
        """Deserialize job from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def calculate_retry_delay(self) -> float:
        """Calculate delay before next retry using exponential backoff."""
        return self.retry_delay * (self.retry_backoff ** (self.attempts - 1))

    def can_retry(self) -> bool:
        """Check if job can be retried."""
        return self.attempts <= self.max_retries

    @property
    def duration_ms(self) -> int | None:
        """Calculate job duration in milliseconds."""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None

    def mark_queued(self, message: str | None = None) -> None:
        """Mark job as queued."""
        self.status = JobStatus.QUEUED
        self._record_transition(JobStatus.QUEUED, message or "Job enqueued")

    def mark_started(self, worker_id: str) -> None:
        """Mark job as started."""
        self.status = JobStatus.ACTIVE
        self.started_at = _utc_now()
        self.worker_id = worker_id
        self.attempts += 1
        self._record_transition(
            JobStatus.ACTIVE,
            f"Started (attempt {self.attempts})",
            worker_id=worker_id,
        )

    def mark_complete(self, result: Any = None) -> None:
        """Mark job as complete."""
        self.status = JobStatus.COMPLETE
        self.completed_at = _utc_now()
        self.result = result
        self.progress = 1.0
        self._record_transition(JobStatus.COMPLETE, "Completed successfully")

    def mark_failed(self, error: str, traceback: str | None = None) -> None:
        """Mark job as failed."""
        self.status = JobStatus.FAILED
        self.completed_at = _utc_now()
        self.error = error
        self.error_traceback = traceback
        self._record_transition(JobStatus.FAILED, f"Failed: {error[:100]}")

    def mark_cancelled(self) -> None:
        """Mark job as cancelled."""
        self.status = JobStatus.CANCELLED
        self.completed_at = _utc_now()
        self._record_transition(JobStatus.CANCELLED, "Cancelled")

    def mark_retrying(self, delay: float) -> None:
        """Mark job as retrying."""
        self.status = JobStatus.RETRYING
        self._record_transition(
            JobStatus.RETRYING,
            f"Scheduled for retry in {delay:.1f}s (attempt {self.attempts + 1})",
        )

    @property
    def is_cron(self) -> bool:
        """Check if this is a recurring cron job.

        Cron jobs are identified by the presence of a recurring schedule.
        """
        return self.job_type == JobType.CRON
