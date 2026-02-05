"""SQLAlchemy models for Conduit persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class JobHistory(Base):
    """
    Completed job history stored in PostgreSQL.

    Jobs are written here after completion (success, failure, or cancellation).
    Used for dashboards, analytics, and debugging.
    """

    __tablename__ = "job_history"

    # Primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Job identity
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    function: Mapped[str] = mapped_column(String(255), nullable=False)

    # Status
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

    # Progress
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # Data (stored as JSON)
    kwargs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # State history for timeline tracking
    state_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Indexes for common queries
    __table_args__ = (
        Index("ix_job_history_function", "function"),
        Index("ix_job_history_status", "status"),
        Index("ix_job_history_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<JobHistory(id={self.id!r}, function={self.function!r}, status={self.status!r})>"
