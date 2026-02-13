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

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from shared.keys import EVENTS_STREAM

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
    retry_attempts: int = 3
    retry_base_delay_seconds: float = 0.025
    retry_max_delay_seconds: float = 0.5
    pending_buffer_size: int = 10_000
    pending_flush_batch_size: int = 128
    durable_buffer_key: str | None = None
    durable_buffer_maxlen: int = 10_000
    strict: bool = False


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
        self._pending: deque[dict[str, str]] = deque()
        self._dropped_pending = 0
        self._durable_lock_ttl_seconds = 5

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def dropped_pending_count(self) -> int:
        return self._dropped_pending

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
        payload = {
            "type": event_type,
            "job_id": job_id,
            "worker_id": self._worker_id,
            "ts": str(time.time()),
            "data": json.dumps(data, default=str),
        }

        await self._flush_pending()
        try:
            await self._publish_with_retry(payload)
        except Exception as e:
            buffered_durably = await self._buffer_pending_durable(payload)
            if not buffered_durably:
                self._buffer_pending(payload)
            message = (
                f"Failed to publish status event {event_type} for job {job_id}: {e}; "
                f"buffered={len(self._pending)} dropped={self._dropped_pending}"
            )
            if self._config.strict:
                raise RuntimeError(message) from e
            logger.warning(message)

    async def _flush_pending(self) -> None:
        await self._flush_durable_pending()
        if not self._pending:
            return

        flushed = 0
        while self._pending and flushed < self._config.pending_flush_batch_size:
            payload = self._pending[0]
            try:
                await self._publish_with_retry(payload)
            except Exception:
                return
            self._pending.popleft()
            flushed += 1

    async def flush_pending(self) -> None:
        """Best-effort flush of both durable and in-memory pending payloads."""
        await self._flush_pending()

    async def close(self, *, timeout_seconds: float = 2.0) -> None:
        """Flush pending status payloads before shutdown."""
        deadline = time.monotonic() + max(0.1, timeout_seconds)
        while time.monotonic() < deadline:
            before_memory = len(self._pending)
            before_durable = await self._durable_pending_count()
            if before_memory == 0 and before_durable == 0:
                return
            await self._flush_pending()
            after_memory = len(self._pending)
            after_durable = await self._durable_pending_count()
            if before_memory == after_memory and before_durable == after_durable:
                break

    async def _buffer_pending_durable(self, payload: dict[str, str]) -> bool:
        key = self._config.durable_buffer_key
        if not key:
            return False
        try:
            encoded = json.dumps(payload)
            maxlen = max(1, self._config.durable_buffer_maxlen)
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.rpush(key, encoded)
                pipe.ltrim(key, -maxlen, -1)
                await pipe.execute()
            return True
        except Exception:
            return False

    async def _flush_durable_pending(self) -> None:
        key = self._config.durable_buffer_key
        if not key:
            return
        lock_key = f"{key}:flush_lock"
        lock_token = f"{self._worker_id}:{time.time_ns()}"
        acquired = await self._acquire_durable_lock(lock_key, lock_token)
        if not acquired:
            return

        try:
            flushed = 0
            max_batch = max(1, self._config.pending_flush_batch_size)
            while flushed < max_batch:
                encoded = await self._redis.lindex(key, 0)
                if encoded is None:
                    return
                if isinstance(encoded, bytes):
                    encoded = encoded.decode()
                try:
                    payload = json.loads(encoded)
                    if not isinstance(payload, dict):
                        raise TypeError("invalid durable payload")
                    await self._publish_with_retry(payload)
                except Exception:
                    return
                await self._redis.lpop(key)
                flushed += 1
        finally:
            await self._release_durable_lock(lock_key, lock_token)

    async def _durable_pending_count(self) -> int:
        key = self._config.durable_buffer_key
        if not key:
            return 0
        try:
            return int(await self._redis.llen(key) or 0)
        except Exception:
            return 0

    async def _acquire_durable_lock(self, lock_key: str, lock_token: str) -> bool:
        try:
            acquired = await self._redis.set(
                lock_key,
                lock_token,
                nx=True,
                ex=self._durable_lock_ttl_seconds,
            )
            return bool(acquired)
        except Exception:
            return False

    async def _release_durable_lock(self, lock_key: str, lock_token: str) -> None:
        try:
            current = await self._redis.get(lock_key)
            current_str = (
                current.decode() if isinstance(current, bytes) else str(current or "")
            )
            if current_str == lock_token:
                await self._redis.delete(lock_key)
        except Exception:
            return

    async def _publish_with_retry(self, payload: dict[str, str]) -> None:
        attempts = max(0, self._config.retry_attempts)
        base_delay = max(0.0, self._config.retry_base_delay_seconds)
        max_delay = max(base_delay, self._config.retry_max_delay_seconds)

        for attempt in range(attempts + 1):
            try:
                await self._publish_once(payload)
                return
            except TypeError:
                # Compatibility fallback for redis/fakeredis variants
                # that don't support the approximate trim argument.
                await self._redis.xadd(
                    self._config.stream,
                    payload,
                    maxlen=self._config.max_stream_len,
                )
                return
            except Exception:
                if attempt >= attempts:
                    raise
                delay = min(max_delay, base_delay * (2**attempt))
                if delay > 0:
                    await asyncio.sleep(delay)

    async def _publish_once(self, payload: dict[str, str]) -> None:
        await self._redis.xadd(
            self._config.stream,
            payload,
            maxlen=self._config.max_stream_len,
            approximate=True,
        )

    def _buffer_pending(self, payload: dict[str, str]) -> None:
        max_size = max(1, self._config.pending_buffer_size)
        if len(self._pending) >= max_size:
            self._pending.popleft()
            self._dropped_pending += 1
        self._pending.append(payload)

    async def record_job_started(
        self,
        job_id: str,
        function: str,
        function_name: str,
        attempt: int,
        max_retries: int,
        root_id: str,
        parent_id: str | None = None,
        source: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        checkpoint_at: str | None = None,
        dlq_replayed_from: str | None = None,
        dlq_failed_at: str | None = None,
        scheduled_at: datetime | None = None,
        queue_wait_ms: float | None = None,
    ) -> None:
        """Record job started event."""
        await self.record(
            "job.started",
            job_id,
            function=function,
            function_name=function_name,
            parent_id=parent_id,
            root_id=root_id,
            source=source or {"type": "task"},
            checkpoint=checkpoint,
            checkpoint_at=checkpoint_at,
            dlq_replayed_from=dlq_replayed_from,
            dlq_failed_at=dlq_failed_at,
            scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
            queue_wait_ms=queue_wait_ms,
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
