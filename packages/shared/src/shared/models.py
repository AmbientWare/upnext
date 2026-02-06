"""Core data models for Conduit."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


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


class JobStatus(str, Enum):
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

    Jobs are the fundamental unit of work in Conduit.
    """

    # Identity
    function: str
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

    # Progress tracking
    progress: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Result
    result: Any = None
    error: str | None = None
    error_traceback: str | None = None

    # Cron scheduling
    schedule: str | None = None

    # State history
    state_history: list[StateTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Set defaults after initialization."""
        if not self.key:
            self.key = self.id

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
        return {
            "id": self.id,
            "key": self.key,
            "function": self.function,
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
            "progress": self.progress,
            "metadata": self.metadata,
            "result": self.result,
            "error": self.error,
            "error_traceback": self.error_traceback,
            "schedule": self.schedule,
            "state_history": [t.to_dict() for t in self.state_history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        """Deserialize job from dictionary."""
        return cls(
            id=data["id"],
            key=data["key"],
            function=data["function"],
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
            progress=data.get("progress", 0.0),
            metadata=data.get("metadata", {}),
            result=data.get("result"),
            error=data.get("error"),
            error_traceback=data.get("error_traceback"),
            schedule=data.get("schedule"),
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

        A job is a cron if it has a schedule AND was marked as cron in metadata.
        This distinguishes cron jobs from regular delayed jobs.
        """
        if self.schedule is None:
            return False
        # Check metadata for explicit cron marker (set by seed_cron/reschedule_cron)
        if self.metadata and self.metadata.get("cron"):
            return True
        # Fallback: if schedule is set, treat as cron for backward compatibility
        return True
