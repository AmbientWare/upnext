"""Dead-letter queue API contract payloads."""

from typing import Any

from pydantic import BaseModel, Field


class DeadLetterEntryResponse(BaseModel):
    """Single dead-letter queue entry."""

    entry_id: str
    function: str
    job_id: str
    failed_at: str | None = None
    reason: str | None = None
    attempts: int = 0
    max_retries: int = 0
    kwargs: dict[str, Any] = Field(default_factory=dict)


class DeadLetterListResponse(BaseModel):
    """List of dead-letter entries for a function."""

    entries: list[DeadLetterEntryResponse]
    total: int
    function: str


class DeadLetterReplayResponse(BaseModel):
    """Response after replaying a dead-letter entry."""

    replayed: bool
    entry_id: str
    new_job_id: str | None = None


class DeadLetterPurgeResponse(BaseModel):
    """Response after purging a function's dead-letter queue."""

    purged: bool
    function: str
    deleted: int


__all__ = [
    "DeadLetterEntryResponse",
    "DeadLetterListResponse",
    "DeadLetterReplayResponse",
    "DeadLetterPurgeResponse",
]
