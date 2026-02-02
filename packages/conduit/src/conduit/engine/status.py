"""Status buffer for batched event reporting.

Instead of sending status updates to the API immediately during job execution,
events are written to a Redis stream and flushed in batches. This provides:

- Non-blocking job execution (Redis writes are microseconds)
- Batched API calls (100 events in 1 request instead of 100 requests)
- Fault tolerance (any worker can flush, dead worker events recovered via XAUTOCLAIM)
- Resilience (if API is down, events buffer safely in Redis)

Example:
    buffer = StatusBuffer(redis_client, worker_id="worker-1")

    # Fast write during job execution
    await buffer.record("started", job_id="job_123", function="process_data")

    # Background flush loop (any worker can run this)
    asyncio.create_task(buffer.flush_loop(backend, interval=2.0))
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from conduit.engine.backend import BaseBackend
    from conduit.engine.database.base import Storage

logger = logging.getLogger(__name__)


@dataclass
class StatusEvent:
    """A status event to be sent to the API."""

    type: str  # "started", "completed", "failed", "progress", "log", "checkpoint", etc.
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
class StatusBufferConfig:
    """Configuration for status buffering."""

    # How often to flush events to API (seconds)
    flush_interval: float = 2.0

    # Maximum events per batch
    batch_size: int = 100

    # Maximum stream length (safety cap to prevent unbounded growth)
    max_stream_len: int = 50000

    # Idle time before claiming events from dead workers (ms)
    stale_claim_ms: int = 30000


class StatusBuffer:
    """
    Buffers status events in Redis for batched API reporting.

    All workers write to a shared stream. Any worker can flush events
    using consumer groups, providing fault tolerance and load balancing.
    """

    STREAM = "conduit:status:events"
    GROUP = "status-flushers"

    def __init__(
        self,
        redis_client: Any,  # redis.asyncio.Redis
        worker_id: str,
        config: StatusBufferConfig | None = None,
    ) -> None:
        self._redis = redis_client
        self._worker_id = worker_id
        self._config = config or StatusBufferConfig()
        self._running = False
        self._group_created = False

    def stop(self) -> None:
        """Signal the flush loop to stop."""
        self._running = False

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
            await self._redis.xadd(
                self.STREAM,
                {
                    "type": event_type,
                    "job_id": job_id,
                    "worker_id": self._worker_id,
                    "ts": str(time.time()),
                    "data": json.dumps(data),
                },
                maxlen=self._config.max_stream_len,
            )
        except Exception as e:
            # Don't fail job execution if status recording fails
            logger.debug(f"Failed to record status event: {e}")

    async def record_job_started(
        self,
        job_id: str,
        function: str,
        attempt: int,
        max_retries: int,
    ) -> None:
        """Record job started event."""
        await self.record(
            "job.started",
            job_id,
            function=function,
            attempt=attempt,
            max_retries=max_retries,
            started_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_completed(
        self,
        job_id: str,
        function: str,
        result: Any = None,
        duration_ms: float | None = None,
    ) -> None:
        """Record job completed event."""
        await self.record(
            "job.completed",
            job_id,
            function=function,
            result=self._serialize_value(result),
            duration_ms=duration_ms,
            completed_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_failed(
        self,
        job_id: str,
        function: str,
        error: str,
        traceback: str | None = None,
        will_retry: bool = False,
    ) -> None:
        """Record job failed event."""
        await self.record(
            "job.failed",
            job_id,
            function=function,
            error=error,
            traceback=traceback,
            will_retry=will_retry,
            failed_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_retrying(
        self,
        job_id: str,
        function: str,
        error: str,
        delay: float,
        current_attempt: int,
        next_attempt: int,
    ) -> None:
        """Record job retrying event."""
        await self.record(
            "job.retrying",
            job_id,
            function=function,
            error=error,
            delay_seconds=delay,
            current_attempt=current_attempt,
            next_attempt=next_attempt,
            retry_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_progress(
        self,
        job_id: str,
        progress: float,
        message: str | None = None,
    ) -> None:
        """Record job progress event."""
        await self.record(
            "job.progress",
            job_id,
            progress=progress,
            message=message,
            updated_at=datetime.now(UTC).isoformat(),
        )

    async def record_job_log(
        self,
        job_id: str,
        level: str,
        message: str,
        **extra: Any,
    ) -> None:
        """Record job log event."""
        await self.record(
            "job.log",
            job_id,
            level=level,
            message=message,
            extra=extra,
            timestamp=datetime.now(UTC).isoformat(),
        )

    async def record_job_checkpoint(
        self,
        job_id: str,
        state: dict[str, Any],
    ) -> None:
        """Record job checkpoint event."""
        await self.record(
            "job.checkpoint",
            job_id,
            state=state,
            checkpointed_at=datetime.now(UTC).isoformat(),
        )

    async def flush_loop(
        self,
        backend: "BaseBackend | None" = None,
        storage: "Storage | None" = None,
    ) -> None:
        """
        Background task to flush events to targets (API and/or storage).

        Uses consumer groups so any worker can flush. If a worker dies,
        another can claim its pending events via XAUTOCLAIM.

        Args:
            backend: Optional BaseBackend instance for sending events to API
            storage: Optional Storage instance for persisting events locally
        """
        if not backend and not storage:
            logger.warning("No flush targets configured, status buffer disabled")
            return
        self._running = True
        await self._ensure_consumer_group()

        logger.debug(
            f"Status buffer flush loop started "
            f"(interval={self._config.flush_interval}s, batch={self._config.batch_size})"
        )

        consecutive_failures = 0
        max_backoff = 60.0

        while self._running:
            try:
                await self._flush_once(backend=backend, storage=storage)
                if consecutive_failures > 0:
                    logger.info("Status flush: connection restored")
                consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                backoff = min(1.0 * (2**consecutive_failures), max_backoff)
                logger.warning(
                    f"Status flush error: {e}, retrying in {backoff:.1f}s "
                    f"(attempt {consecutive_failures})"
                )
                await asyncio.sleep(backoff)

        # Final flush on shutdown
        try:
            await self._flush_once(backend=backend, storage=storage, final=True)
        except Exception:
            pass

        logger.debug("Status buffer flush loop stopped")

    async def _flush_once(
        self,
        backend: "BaseBackend | None" = None,
        storage: "Storage | None" = None,
        final: bool = False,
    ) -> None:
        """
        Perform one flush cycle.

        Accumulates events until batch is full OR timeout expires (whichever first).
        This gives low latency under high load and efficient batching under low load.
        """
        events: list[tuple[str, dict[str, Any]]] = []
        event_ids: list[str] = []

        # Accumulate events until batch full or timeout
        start_time = time.time()
        timeout_ms = int(self._config.flush_interval * 1000)

        while self._running and len(events) < self._config.batch_size:
            elapsed_ms = int((time.time() - start_time) * 1000)
            remaining_ms = timeout_ms - elapsed_ms

            if remaining_ms <= 0:
                break

            # Block for short periods to stay responsive to stop signals
            block_ms = min(50, remaining_ms) if not final else 0

            try:
                result = await self._redis.xreadgroup(
                    self.GROUP,
                    self._worker_id,
                    {self.STREAM: ">"},
                    count=self._config.batch_size - len(events),
                    block=block_ms,
                )
                if result:
                    for _, stream_events in result:
                        for event_id, event_data in stream_events:
                            eid = (
                                event_id.decode()
                                if isinstance(event_id, bytes)
                                else event_id
                            )
                            event_ids.append(eid)
                            events.append((eid, self._decode_event_data(event_data)))
            except Exception as e:
                logger.debug(f"Error reading from status stream: {e}")
                break

        # Claim stale events from dead workers
        try:
            claimed = await self._redis.xautoclaim(
                self.STREAM,
                self.GROUP,
                self._worker_id,
                min_idle_time=self._config.stale_claim_ms,
                count=self._config.batch_size,
            )
            # xautoclaim returns (next_id, [(id, data), ...], [deleted_ids])
            if claimed and len(claimed) >= 2:
                for event_id, event_data in claimed[1]:
                    eid = event_id.decode() if isinstance(event_id, bytes) else event_id
                    if eid not in event_ids:
                        event_ids.append(eid)
                        events.append((eid, self._decode_event_data(event_data)))
        except Exception as e:
            logger.debug(f"Error claiming stale events: {e}")

        if not events:
            return

        # Convert to StatusEvent objects
        status_events = []
        for event_id, data in events:
            try:
                status_events.append(
                    StatusEvent(
                        type=data.get("type", "unknown"),
                        job_id=data.get("job_id", ""),
                        worker_id=data.get("worker_id", ""),
                        timestamp=float(data.get("ts", time.time())),
                        data=json.loads(data.get("data", "{}")),
                    )
                )
            except Exception as e:
                logger.debug(f"Error parsing status event: {e}")

        if not status_events:
            # ACK unparseable events to avoid infinite loop
            await self._ack_events(event_ids)
            return

        # Send batch to targets
        try:
            # Send to API backend if configured
            if backend:
                await backend.batch_send(status_events)

            await self._ack_events(event_ids)
            logger.debug(f"Flushed {len(status_events)} status events")
        except Exception as e:
            # Don't ACK - events will be retried
            logger.warning(f"Failed to send status batch: {e}")

    async def _ack_events(self, event_ids: list[str]) -> None:
        """Acknowledge processed events."""
        if event_ids:
            try:
                await self._redis.xack(self.STREAM, self.GROUP, *event_ids)
            except Exception as e:
                logger.debug(f"Error ACKing events: {e}")

    async def _ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist."""
        if self._group_created:
            return

        try:
            await self._redis.xgroup_create(
                self.STREAM,
                self.GROUP,
                id="0",
                mkstream=True,
            )
            logger.debug(f"Created consumer group '{self.GROUP}'")
        except Exception as e:
            # Group may already exist
            if "BUSYGROUP" not in str(e):
                logger.debug(f"Consumer group creation: {e}")

        self._group_created = True

    def _decode_event_data(
        self, data: dict[bytes | str, bytes | str]
    ) -> dict[str, str]:
        """Decode bytes to strings in event data."""
        result = {}
        for k, v in data.items():
            key = k.decode() if isinstance(k, bytes) else k
            value = v.decode() if isinstance(v, bytes) else v
            result[key] = value
        return result

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a value for JSON transport."""
        if value is None:
            return None
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)

    async def get_pending_count(self) -> int:
        """Get count of pending (unprocessed) events."""
        try:
            info = await self._redis.xpending(self.STREAM, self.GROUP)
            return info.get("pending", 0) if info else 0
        except Exception:
            return 0

    async def get_stream_length(self) -> int:
        """Get total length of the status stream."""
        try:
            return await self._redis.xlen(self.STREAM)
        except Exception:
            return 0
