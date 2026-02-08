"""SQLAlchemy models for Conduit persistence."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class JobHistory(Base):
    """
    Job history stored in database.

    Jobs are written here during execution and updated on completion.
    Used for dashboards, analytics, and debugging.
    """

    __tablename__ = "job_history"

    # Primary key (job_id)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Job identity
    function: Mapped[str] = mapped_column(String(255), nullable=False)
    function_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Status: active, complete, failed, retrying
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
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
        Index("ix_job_history_status", "status"),
        Index("ix_job_history_created_at", "created_at"),
        Index("ix_job_history_worker_id", "worker_id"),
        Index("ix_job_history_parent_id", "parent_id"),
        Index("ix_job_history_root_id", "root_id"),
    )

    def __repr__(self) -> str:
        return f"<JobHistory(id={self.id!r}, function={self.function!r}, status={self.status!r})>"


class Artifact(Base):
    """
    Job artifacts (files, images, data) stored during execution.

    Artifacts are associated with a job and can be retrieved later
    for debugging, analysis, or display in dashboards.
    """

    __tablename__ = "artifacts"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to job
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_history.id", ondelete="CASCADE"), nullable=False
    )

    # Artifact identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # text, json, image/png, file/pdf, etc.

    # Content
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[Any] = mapped_column(JSON, nullable=True)  # For small JSON/text data
    path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # For file references

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    job: Mapped["JobHistory"] = relationship("JobHistory", back_populates="artifacts")

    # Indexes
    __table_args__ = (
        Index("ix_artifacts_job_id", "job_id"),
        Index("ix_artifacts_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id!r}, job_id={self.job_id!r}, name={self.name!r})>"


class PendingArtifact(Base):
    """
    Staging table for artifacts received before job_history exists.

    Rows are promoted into artifacts once the corresponding job row is persisted.
    """

    __tablename__ = "pending_artifacts"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Job linkage (no FK by design to allow pre-job buffering)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Artifact identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Content
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[Any] = mapped_column(JSON, nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

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
