"""SQLAlchemy models for UpNext persistence."""

import uuid
from datetime import UTC, datetime
from typing import Any

from shared.contracts import (
    CronJobSource,
    EventJobSource,
    JobSource,
    TaskJobSource,
)
from shared.domain import JobType
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class JobHistory(Base):
    """
    Job history stored in database.

    Jobs are written here during execution and updated on completion.
    Used for dashboards, analytics, and debugging.
    """

    __tablename__ = "job_history"

    # Job IDs come from the runtime/queue; do not auto-generate in DB.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Job identity
    function: Mapped[str] = mapped_column(String(255), nullable=False)
    function_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(String(20), nullable=False, default="task")

    # Status: active, complete, failed, retrying
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Timing
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    queue_wait_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Execution
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    timeout: Mapped[float | None] = mapped_column(Float, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    root_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Progress (0.0 to 1.0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # Data (stored as JSON)
    kwargs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cron_window_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    startup_reconciled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    startup_policy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    checkpoint_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dlq_replayed_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dlq_failed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_handler_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", back_populates="job", cascade="all, delete-orphan"
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_job_history_function", "function"),
        Index("ix_job_history_function_name", "function_name"),
        Index("ix_job_history_job_type", "job_type"),
        Index("ix_job_history_status", "status"),
        Index("ix_job_history_created_at", "created_at"),
        Index("ix_job_history_worker_id", "worker_id"),
        Index("ix_job_history_parent_id", "parent_id"),
        Index("ix_job_history_root_id", "root_id"),
    )

    def __repr__(self) -> str:
        return f"<JobHistory(id={self.id!r}, function={self.function!r}, status={self.status!r})>"

    @property
    def duration_ms(self) -> float | None:
        """Derived runtime duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    @property
    def source(self) -> JobSource:
        """Normalized typed source used by API response models."""
        try:
            job_type = JobType(self.job_type)
        except (TypeError, ValueError):
            return TaskJobSource()

        if job_type == JobType.CRON and self.schedule:
            return CronJobSource(
                schedule=self.schedule,
                cron_window_at=self.cron_window_at,
                startup_reconciled=self.startup_reconciled,
                startup_policy=self.startup_policy,
            )

        if job_type == JobType.EVENT and self.event_pattern and self.event_handler_name:
            return EventJobSource(
                event_pattern=self.event_pattern,
                event_handler_name=self.event_handler_name,
            )

        return TaskJobSource()


class Artifact(Base):
    """
    Job artifacts (files, images, data) stored during execution.

    Artifacts are associated with a job and can be retrieved later
    for debugging, analysis, or display in dashboards.
    """

    __tablename__ = "artifacts"

    # Foreign key to job
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_history.id", ondelete="CASCADE"), nullable=False
    )

    # Artifact identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # text, json, image/png, file/pdf, etc.

    # Content metadata
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(700), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    job: Mapped["JobHistory"] = relationship("JobHistory", back_populates="artifacts")

    # Indexes
    __table_args__ = (
        Index("ix_artifacts_job_id", "job_id"),
        Index("ix_artifacts_name", "name"),
        Index("ix_artifacts_storage", "storage_backend", "storage_key"),
    )

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id!r}, job_id={self.job_id!r}, name={self.name!r})>"


class PendingArtifact(Base):
    """
    Staging table for artifacts received before job_history exists.

    Rows are promoted into artifacts once the corresponding job row is persisted.
    """

    __tablename__ = "pending_artifacts"

    # Job linkage (no FK by design to allow pre-job buffering)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Artifact identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Content metadata
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(700), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Indexes
    __table_args__ = (
        Index("ix_pending_artifacts_job_id", "job_id"),
        Index("ix_pending_artifacts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<PendingArtifact(id={self.id!r}, job_id={self.job_id!r}, "
            f"name={self.name!r})>"
        )
