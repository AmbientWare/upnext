"""Status buffer for writing events to Redis stream.

Workers write status events to a Redis stream for the server to consume.
The server's stream subscriber reads from this stream and writes to the database.

This provides:
- Non-blocking job execution (Redis writes are microseconds)
- Decoupled workers (no HTTP calls to API)
- Fault tolerance (server can recover events if it restarts)
- Resilience (if server is down, events buffer safely in Redis)

Example:
    buffer = StatusPublisher(redis_client, worker_id="worker-1")

    # Fast write during job execution
    await buffer.record("started", job_id="job_123", function="process_data")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from shared.events import EVENTS_STREAM

logger = logging.getLogger(__name__)


@dataclass
class StatusEvent:
    """A status event to be sent to the API."""

    type: str  # "started", "completed", "failed", "progress", "checkpoint", etc.
    job_id: str
    worker_id: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type,
            "job_id": self.job_id,
            "worker_id": self.worker_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StatusEvent":
        """Create from dictionary."""
        return cls(
            type=d["type"],
            job_id=d["job_id"],
            worker_id=d["worker_id"],
            timestamp=d.get("timestamp", time.time()),
            data=d.get("data", {}),
        )


@dataclass
class StatusPublisherConfig:
    """Configuration for status buffering."""

    # Maximum stream length (safety cap to prevent unbounded growth)
    max_stream_len: int = 50000
    stream: str = EVENTS_STREAM


class StatusPublisher:
    """
    Writes status events to Redis stream for server consumption.

    Workers use this to record job events (started, completed, failed, etc.)
    which are written to a shared Redis stream. The server's stream subscriber
    reads from this stream and persists events to the database.
    """

    def __init__(
        self,
        redis_client: Any,  # redis.asyncio.Redis
        worker_id: str,
        config: StatusPublisherConfig | None = None,
    ) -> None:
        self._redis = redis_client
        self._worker_id = worker_id
        self._config = config or StatusPublisherConfig()

    async def record(
        self,
        event_type: str,
        job_id: str,
        **data: Any,
    ) -> None:
        """
        Record a status event (fast, non-blocking write to Redis).

        Args:
            event_type: Type of event (started, completed, failed, progress, etc.)
            job_id: Job ID this event relates to
            **data: Additional event data
        """
        try:
            payload = {
                "type": event_type,
                "job_id": job_id,
                "worker_id": self._worker_id,
                "ts": str(time.time()),
                "data": json.dumps(data, default=str),
            }
            try:
                await self._redis.xadd(
                    self._config.stream,
                    payload,
                    maxlen=self._config.max_stream_len,
                    approximate=True,
                )
            except TypeError:
                # Compatibility fallback for redis/fakeredis variants
                # that don't support the approximate trim argument.
                await self._redis.xadd(
                    self._config.stream,
                    payload,
                    maxlen=self._config.max_stream_len,
                )
        except Exception as e:
            # Don't fail job execution if status recording fails
            logger.debug(f"Failed to record status event: {e}")

    async def record_job_started(
        self,
        job_id: str,
        function: str,
        function_name: str,
        attempt: int,
        max_retries: int,
        root_id: str,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record job started event."""
        await self.record(
            "job.started",
            job_id,
            function=function,
            function_name=function_name,
            parent_id=parent_id,
            root_id=root_id,
            metadata=metadata or {},
            attempt=attempt,
            max_retries=max_retries,
            started_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_completed(
        self,
        job_id: str,
        function: str,
        function_name: str,
        root_id: str,
        parent_id: str | None = None,
        attempt: int = 1,
        result: Any = None,
        duration_ms: float | None = None,
    ) -> None:
        """Record job completed event."""
        await self.record(
            "job.completed",
            job_id,
            function=function,
            function_name=function_name,
            parent_id=parent_id,
            root_id=root_id,
            attempt=attempt,
            result=self._serialize_value(result),
            duration_ms=duration_ms,
            completed_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_failed(
        self,
        job_id: str,
        function: str,
        function_name: str,
        root_id: str,
        error: str,
        attempt: int = 1,
        max_retries: int = 0,
        parent_id: str | None = None,
        traceback: str | None = None,
        will_retry: bool = False,
    ) -> None:
        """Record job failed event."""
        await self.record(
            "job.failed",
            job_id,
            function=function,
            function_name=function_name,
            parent_id=parent_id,
            root_id=root_id,
            error=error,
            attempt=attempt,
            max_retries=max_retries,
            traceback=traceback,
            will_retry=will_retry,
            failed_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_retrying(
        self,
        job_id: str,
        function: str,
        function_name: str,
        root_id: str,
        error: str,
        delay: float,
        current_attempt: int,
        next_attempt: int,
        parent_id: str | None = None,
    ) -> None:
        """Record job retrying event."""
        await self.record(
            "job.retrying",
            job_id,
            function=function,
            function_name=function_name,
            parent_id=parent_id,
            root_id=root_id,
            error=error,
            delay_seconds=delay,
            current_attempt=current_attempt,
            next_attempt=next_attempt,
            retry_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_progress(
        self,
        job_id: str,
        root_id: str,
        progress: float,
        parent_id: str | None = None,
        message: str | None = None,
    ) -> None:
        """Record job progress event."""
        await self.record(
            "job.progress",
            job_id,
            parent_id=parent_id,
            root_id=root_id,
            progress=progress,
            message=message,
            updated_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_checkpoint(
        self,
        job_id: str,
        root_id: str,
        state: dict[str, Any],
        parent_id: str | None = None,
    ) -> None:
        """Record job checkpoint event."""
        await self.record(
            "job.checkpoint",
            job_id,
            parent_id=parent_id,
            root_id=root_id,
            state=state,
            checkpointed_at=datetime.now(UTC).isoformat(),
        )

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a value for JSON transport."""
        if value is None:
            return None
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)

    async def get_stream_length(self) -> int:
        """Get total length of the status stream."""
        try:
            return await self._redis.xlen(self._config.stream)
        except Exception:
            return 0
