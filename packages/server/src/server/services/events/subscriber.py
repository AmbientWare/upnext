"""Redis stream subscriber for status events.

Subscribes to the upnext:status:events stream and processes events
directly to the database. This replaces HTTP-based event ingestion
for improved performance and decoupling.

The subscriber uses Redis consumer groups for:
- Load balancing across multiple server instances
- Fault tolerance (automatic failover of pending events)
- At-least-once delivery semantics
"""

import asyncio
import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeAlias

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.typing import EncodableT, FieldT
from shared.contracts import (
    EventProcessingStats,
    EventType,
    JobCancelledEvent,
    JobCheckpointEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobRetryingEvent,
    JobStartedEvent,
    SSEJobEvent,
    StatusStreamEvent,
)
from shared.keys import EVENTS_PUBSUB_CHANNEL, EVENTS_STREAM

from server.db.session import get_database
from server.services.events.processing import process_event

logger = logging.getLogger(__name__)


JobLifecycleEvent: TypeAlias = (
    JobStartedEvent
    | JobCompletedEvent
    | JobFailedEvent
    | JobCancelledEvent
    | JobRetryingEvent
    | JobProgressEvent
    | JobCheckpointEvent
)


@dataclass(frozen=True)
class _ParsedEvent:
    event_id: str
    event_type: EventType
    event: JobLifecycleEvent
    worker_id: str


@dataclass(frozen=True)
class _InvalidEventRecord:
    event_id: str
    reason: str
    raw: dict[str, Any]
    error: str
    worker_id: str | None = None
    event_type: str | None = None


@dataclass(frozen=True)
class _ParseDiscardSummary:
    invalid_events: list[_InvalidEventRecord]
    invalid_envelope: int = 0
    invalid_payload: int = 0
    unsupported_type: int = 0

    @property
    def total(self) -> int:
        return self.invalid_envelope + self.invalid_payload + self.unsupported_type


@dataclass
class StreamSubscriberConfig:
    """Configuration for the stream subscriber."""

    # Stream name (must match worker StatusPublisher.STREAM)
    stream: str = EVENTS_STREAM

    # Consumer group name
    group: str = "server-subscribers"

    # Maximum events to read per batch
    batch_size: int = 100

    # How often to check for events when idle (seconds)
    poll_interval: float = 2.0

    # Time before claiming events from dead consumers (ms)
    stale_claim_ms: int = 30000

    # Dead-letter stream for malformed/unsupported events.
    invalid_events_stream: str = f"{EVENTS_STREAM}:invalid"
    invalid_events_stream_maxlen: int = 10_000

    # Consumer ID (auto-generated if None)
    consumer_id: str | None = None


class StreamSubscriber:
    """
    Subscribes to Redis status events stream and writes to database.

    Runs as a background task that:
    1. Reads events from the stream using XREADGROUP
    2. Claims stale events from dead consumers using XAUTOCLAIM
    3. Processes events and writes to PostgreSQL
    4. Acknowledges processed events using XACK

    Example:
        redis_client = await connect_redis()
        subscriber = StreamSubscriber(redis_client=redis_client)
        await subscriber.start()
        # ... server runs ...
        await subscriber.stop()  # graceful shutdown
    """

    def __init__(
        self,
        redis_client: Redis,
        config: StreamSubscriberConfig | None = None,
    ) -> None:
        self._config = config or StreamSubscriberConfig()
        self._redis = redis_client
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._group_created = False
        self._last_batch_event_count = 0
        self._invalid_envelope_total = 0
        self._invalid_payload_total = 0
        self._unsupported_type_total = 0

        # Generate unique consumer ID
        if not self._config.consumer_id:
            hostname = socket.gethostname()
            pid = os.getpid()
            self._config.consumer_id = f"server-{hostname}-{pid}"

    @property
    def is_running(self) -> bool:
        """Check if the subscriber is running."""
        return self._task is not None and not self._task.done()

    @property
    def discarded_event_stats(self) -> EventProcessingStats:
        """Monotonic discard counters useful for diagnostics and alerts."""
        return EventProcessingStats(
            invalid_envelope=self._invalid_envelope_total,
            invalid_payload=self._invalid_payload_total,
            unsupported_type=self._unsupported_type_total,
        )

    async def start(self) -> None:
        """Start the subscriber background task."""
        if self._task is not None:
            return

        await self._ensure_consumer_group()

        self._stop_event.clear()
        self._task = asyncio.create_task(self._subscribe_loop())

        logger.info(
            f"Stream subscriber started "
            f"(consumer={self._config.consumer_id}, "
            f"group={self._config.group}, "
            f"batch_size={self._config.batch_size})"
        )

    async def stop(self) -> None:
        """Stop the subscriber gracefully, draining remaining events."""
        if self._task is None:
            return

        logger.info("Stopping stream subscriber, draining events...")
        self._stop_event.set()

        # Allow time for final drain
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        logger.info("Stream subscriber stopped")

    async def _subscribe_loop(self) -> None:
        """Main subscription loop."""
        consecutive_failures = 0
        max_backoff = 60.0

        while not self._stop_event.is_set():
            try:
                processed_count = await self._process_batch()

                if consecutive_failures > 0:
                    logger.info("Stream subscriber: recovered from errors")
                consecutive_failures = 0

                # Keep draining without an extra sleep while events are flowing.
                if processed_count > 0:
                    continue

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                backoff = min(1.0 * (2**consecutive_failures), max_backoff)
                logger.warning(
                    f"Stream subscriber error: {e}, "
                    f"retrying in {backoff:.1f}s (attempt {consecutive_failures})"
                )
                await asyncio.sleep(backoff)
                continue

            # Brief idle wait to avoid tight loops when no work was processed.
            idle_wait = max(0.05, min(self._config.poll_interval / 4, 0.25))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=idle_wait)
            except asyncio.TimeoutError:
                pass

        # Final drain on shutdown
        logger.debug("Final drain of pending events...")
        try:
            while True:
                if await self._process_batch(drain=True) == 0:
                    break
        except Exception as e:
            logger.warning(f"Error during final drain: {e}")

    async def _process_batch(self, drain: bool = False) -> int:
        """
        Process one batch of events from the stream.

        Args:
            drain: If True, don't block waiting for events

        Returns:
            Number of events processed
        """
        if not await self._ensure_consumer_group():
            return 0

        events: list[tuple[str, dict[str, Any]]] = []
        event_ids: list[str] = []
        ack_ids: list[str] = []
        seen_event_ids: set[str] = set()

        # Read new events
        block_ms = 0 if drain else max(int(self._config.poll_interval * 1000), 1)

        if not self._config.consumer_id:
            raise ValueError("Consumer ID is required")

        try:
            result = await self._redis.xreadgroup(
                self._config.group,
                self._config.consumer_id,
                {self._config.stream: ">"},
                count=self._config.batch_size,
                block=block_ms,
            )
        except Exception as exc:
            raise RuntimeError("Failed reading from status stream") from exc

        if result:
            for _, stream_events in result:
                self._add_stream_events(
                    stream_events,
                    seen_event_ids=seen_event_ids,
                    event_ids=event_ids,
                    events=events,
                )

        # Claim stale events from dead consumers
        if not drain:
            remaining = self._config.batch_size - len(events)
            if remaining > 0:
                try:
                    claimed = await self._redis.xautoclaim(
                        self._config.stream,
                        self._config.group,
                        self._config.consumer_id,
                        min_idle_time=self._config.stale_claim_ms,
                        count=remaining,
                    )
                except Exception as exc:
                    raise RuntimeError("Failed claiming stale status events") from exc

                if claimed and len(claimed) >= 2:
                    claimed_events = claimed[1]
                    self._add_stream_events(
                        claimed_events,
                        seen_event_ids=seen_event_ids,
                        event_ids=event_ids,
                        events=events,
                    )
                    if claimed_events:
                        logger.debug(f"Claimed {len(claimed_events)} stale events")

        if not events:
            self._last_batch_event_count = 0
            return 0

        # Keep processing order stable even when mixing fresh and reclaimed events.
        # Reclaimed events can be older than newly-read events.
        events.sort(key=lambda item: self._event_id_sort_key(item[0]))
        self._last_batch_event_count = len(event_ids)

        parsed_events, discard_summary = self._parse_events(events)
        ack_ids.extend(await self._dead_letter_invalid_events(discard_summary))
        self._invalid_envelope_total += discard_summary.invalid_envelope
        self._invalid_payload_total += discard_summary.invalid_payload
        self._unsupported_type_total += discard_summary.unsupported_type
        coalesced_events, coalesced_ack_ids_by_latest = self._coalesce_progress_events(
            parsed_events
        )

        # Process events
        processed = 0
        errors = 0
        events_for_publish: list[_ParsedEvent] = []
        db = None
        try:
            db = get_database()
        except RuntimeError as exc:
            if "Database not initialized" not in str(exc):
                raise

        if db is None:
            for parsed_event in coalesced_events:
                event_id = parsed_event.event_id
                try:
                    applied = await process_event(event=parsed_event.event)
                    processed += 1
                    ack_ids.append(event_id)
                    ack_ids.extend(coalesced_ack_ids_by_latest.get(event_id, ()))
                    if applied:
                        events_for_publish.append(parsed_event)
                except Exception as e:
                    errors += 1
                    logger.warning(f"Error processing event {event_id}: {e}")
        else:
            async with db.session() as session:
                for parsed_event in coalesced_events:
                    event_id = parsed_event.event_id
                    try:
                        async with session.begin_nested():
                            try:
                                applied = await process_event(
                                    event=parsed_event.event,
                                    session=session,
                                )
                            except TypeError as exc:
                                if "session" not in str(exc):
                                    raise
                                # Backward compatibility for tests/patches that inject a
                                # simpler coroutine signature: fake_process_event(event).
                                applied = await process_event(event=parsed_event.event)
                        processed += 1
                        ack_ids.append(event_id)
                        ack_ids.extend(coalesced_ack_ids_by_latest.get(event_id, ()))
                        if applied:
                            events_for_publish.append(parsed_event)
                    except Exception as e:
                        errors += 1
                        logger.warning(f"Error processing event {event_id}: {e}")

        # ACK only successfully processed events.
        # Failed events stay pending and can be retried/reclaimed later.
        if ack_ids:
            try:
                unique_ack_ids = list(dict.fromkeys(ack_ids))
                await self._redis.xack(
                    self._config.stream, self._config.group, *unique_ack_ids
                )
            except Exception as e:
                logger.warning(f"Error ACKing events: {e}")

        # SSE publish is best-effort and intentionally after ACK so ingest path
        # isn't blocked on realtime fan-out to browser subscribers.
        for parsed_event in events_for_publish:
            try:
                await self._publish_parsed_event(parsed_event)
            except Exception as e:
                logger.debug(
                    "Error publishing parsed event %s after ACK: %s",
                    parsed_event.event_id,
                    e,
                )

        if processed > 0 or errors > 0 or discard_summary.total > 0:
            logger.debug(
                "Processed %s events (%s errors, %s discarded, %s acked, %s pending)",
                processed,
                errors,
                discard_summary.total,
                len(ack_ids),
                len(event_ids) - len(ack_ids),
            )

        return processed

    def _parse_events(
        self, events: list[tuple[str, dict[str, Any]]]
    ) -> tuple[list[_ParsedEvent], _ParseDiscardSummary]:
        parsed_events: list[_ParsedEvent] = []
        invalid_events: list[_InvalidEventRecord] = []
        invalid_envelope = 0
        invalid_payload = 0
        unsupported_type = 0

        for event_id, data in events:
            try:
                stream_event = StatusStreamEvent.model_validate(data)
            except ValidationError as exc:
                logger.warning(
                    "Discarding invalid status stream event %s: %s", event_id, exc
                )
                invalid_events.append(
                    _InvalidEventRecord(
                        event_id=event_id,
                        reason="invalid_envelope",
                        raw=data,
                        error=str(exc),
                    )
                )
                invalid_envelope += 1
                continue

            payload_data: dict[str, Any] = dict(stream_event.data)
            payload_data["job_id"] = stream_event.job_id
            payload_data.pop("type", None)
            if (
                stream_event.type == EventType.JOB_STARTED
                and "worker_id" not in payload_data
            ):
                payload_data["worker_id"] = stream_event.worker_id

            try:
                parsed_event_model = self._parse_event_model(
                    stream_event.type, payload_data
                )
            except ValidationError as exc:
                logger.warning(
                    "Discarding invalid event payload for %s id=%s: %s",
                    stream_event.type.value,
                    event_id,
                    exc,
                )
                invalid_events.append(
                    _InvalidEventRecord(
                        event_id=event_id,
                        reason="invalid_payload",
                        raw=data,
                        error=str(exc),
                        worker_id=stream_event.worker_id,
                        event_type=stream_event.type.value,
                    )
                )
                invalid_payload += 1
                continue

            except ValueError as exc:
                logger.warning(
                    "Discarding unsupported event type %s id=%s: %s",
                    stream_event.type.value,
                    event_id,
                    exc,
                )
                invalid_events.append(
                    _InvalidEventRecord(
                        event_id=event_id,
                        reason="unsupported_type",
                        raw=data,
                        error=str(exc),
                        worker_id=stream_event.worker_id,
                        event_type=stream_event.type.value,
                    )
                )
                unsupported_type += 1
                continue

            parsed_events.append(
                _ParsedEvent(
                    event_id=event_id,
                    event_type=stream_event.type,
                    event=parsed_event_model,
                    worker_id=stream_event.worker_id,
                )
            )

        return (
            parsed_events,
            _ParseDiscardSummary(
                invalid_events=invalid_events,
                invalid_envelope=invalid_envelope,
                invalid_payload=invalid_payload,
                unsupported_type=unsupported_type,
            ),
        )

    async def _dead_letter_invalid_events(
        self,
        summary: _ParseDiscardSummary,
    ) -> list[str]:
        """Write malformed events to invalid stream and ACK only successful writes."""
        if not summary.invalid_events:
            return []

        ack_ids: list[str] = []
        for invalid in summary.invalid_events:
            payload: dict[FieldT, EncodableT] = {
                "event_id": invalid.event_id,
                "reason": invalid.reason,
                "error": invalid.error,
                "received_at": datetime.now(UTC).isoformat(),
                "data": json.dumps(invalid.raw, default=str),
            }
            worker_id = invalid.worker_id
            if worker_id is not None:
                payload["worker_id"] = worker_id
            event_type = invalid.event_type
            if event_type is not None:
                payload["event_type"] = event_type

            try:
                if self._config.invalid_events_stream_maxlen > 0:
                    await self._redis.xadd(
                        self._config.invalid_events_stream,
                        payload,
                        maxlen=self._config.invalid_events_stream_maxlen,
                        approximate=True,
                    )
                else:
                    await self._redis.xadd(self._config.invalid_events_stream, payload)
                ack_ids.append(invalid.event_id)
            except TypeError:
                # Compatibility fallback for redis variants without approximate trim.
                if self._config.invalid_events_stream_maxlen > 0:
                    await self._redis.xadd(
                        self._config.invalid_events_stream,
                        payload,
                        maxlen=self._config.invalid_events_stream_maxlen,
                    )
                else:
                    await self._redis.xadd(self._config.invalid_events_stream, payload)
                ack_ids.append(invalid.event_id)
            except Exception as exc:
                logger.warning(
                    "Failed to dead-letter invalid stream event %s: %s",
                    invalid.event_id,
                    exc,
                )

        return ack_ids

    @staticmethod
    def _parse_event_model(
        event_type: EventType, payload_data: dict[str, Any]
    ) -> JobLifecycleEvent:
        if event_type == EventType.JOB_STARTED:
            return JobStartedEvent.model_validate(payload_data)
        if event_type == EventType.JOB_COMPLETED:
            return JobCompletedEvent.model_validate(payload_data)
        if event_type == EventType.JOB_FAILED:
            return JobFailedEvent.model_validate(payload_data)
        if event_type == EventType.JOB_CANCELLED:
            return JobCancelledEvent.model_validate(payload_data)
        if event_type == EventType.JOB_RETRYING:
            return JobRetryingEvent.model_validate(payload_data)
        if event_type == EventType.JOB_PROGRESS:
            return JobProgressEvent.model_validate(payload_data)
        if event_type == EventType.JOB_CHECKPOINT:
            return JobCheckpointEvent.model_validate(payload_data)
        raise ValueError(f"Unsupported event type: {event_type!r}")

    def _coalesce_progress_events(
        self,
        events: list[_ParsedEvent],
    ) -> tuple[list[_ParsedEvent], dict[str, list[str]]]:
        """Coalesce duplicate progress updates within one batch.

        Keeps only the latest contiguous ``job.progress`` event for each job.
        Any non-progress event for a job acts as a barrier and resets coalescing
        for that job to preserve lifecycle ordering around state transitions.
        """

        coalesced: list[_ParsedEvent] = []
        coalesced_ack_ids_by_latest: dict[str, list[str]] = {}
        latest_progress_index_by_job: dict[str, int] = {}

        for event in events:
            event_id = event.event_id
            event_type = event.event_type
            job_id = event.event.job_id

            if event_type != EventType.JOB_PROGRESS or not job_id:
                if job_id:
                    latest_progress_index_by_job.pop(job_id, None)
                coalesced.append(event)
                continue

            existing_index = latest_progress_index_by_job.get(job_id)
            if existing_index is None:
                latest_progress_index_by_job[job_id] = len(coalesced)
                coalesced.append(event)
                continue

            previous_event_id = coalesced[existing_index].event_id
            coalesced[existing_index] = event
            coalesced_ack_ids_by_latest.setdefault(event_id, []).append(
                previous_event_id
            )
            if prior_ids := coalesced_ack_ids_by_latest.pop(previous_event_id, None):
                coalesced_ack_ids_by_latest[event_id].extend(prior_ids)

        return coalesced, coalesced_ack_ids_by_latest

    @staticmethod
    def _event_id_sort_key(event_id: str) -> tuple[int, int]:
        """Parse Redis stream event IDs ("<ms>-<seq>") for chronological sorting."""
        try:
            ms_str, seq_str = event_id.split("-", 1)
            return (int(ms_str), int(seq_str))
        except (ValueError, TypeError):
            # Keep malformed IDs last, preserving behavior for normal IDs.
            max_id = 2**63 - 1
            return (max_id, max_id)

    async def _handle_event(self, parsed_event: _ParsedEvent) -> None:
        """Process a single event by writing to database and publishing to SSE."""
        applied = await process_event(event=parsed_event.event)
        if applied:
            await self._publish_parsed_event(parsed_event)

    async def _publish_parsed_event(self, parsed_event: _ParsedEvent) -> None:
        """Publish a parsed event for SSE consumers."""
        event_data = parsed_event.event.model_dump(mode="python")
        await self._publish_event(
            parsed_event.event_type.value,
            event_data,
            parsed_event.worker_id,
        )

    async def _publish_event(
        self,
        event_type: str,
        data: dict[str, Any],
        worker_id: str,
    ) -> None:
        """Publish event data for SSE consumers.

        Uses SSEJobEvent to filter to safe fields only — kwargs, result,
        traceback, and checkpoint state are excluded automatically.
        """
        try:
            event = SSEJobEvent(
                type=event_type,
                worker_id=worker_id,
                **data,
            )
            await self._redis.publish(
                EVENTS_PUBSUB_CHANNEL,
                event.model_dump_json(exclude_none=True),
            )
        except Exception as e:
            logger.debug(f"Error publishing event: {e}")

    async def _ensure_consumer_group(self) -> bool:
        """Create consumer group if it doesn't exist."""
        if self._group_created:
            return True

        try:
            await self._redis.xgroup_create(
                self._config.stream,
                self._config.group,
                id="0",  # Start from beginning of stream
                mkstream=True,
            )
            logger.debug(f"Created consumer group '{self._config.group}'")
            self._group_created = True
            return True

        except Exception as e:
            # BUSYGROUP means group already exists - that's fine
            if "BUSYGROUP" in str(e):
                self._group_created = True
                return True
            logger.warning(f"Consumer group creation issue: {e}")
            return False

    def _decode_event_data(
        self,
        data: dict[Any, Any],
    ) -> dict[str, object]:
        """Decode bytes keys/values while preserving non-bytes value types."""
        result: dict[str, object] = {}
        for k, v in data.items():
            key = k.decode() if isinstance(k, bytes) else str(k)
            value: object = v.decode() if isinstance(v, bytes) else v
            result[key] = value
        return result

    def _add_stream_events(
        self,
        stream_events: list[tuple[Any, dict[Any, Any]]],
        *,
        seen_event_ids: set[str],
        event_ids: list[str],
        events: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Decode and append unique stream events while preserving input order."""
        for raw_event_id, raw_event_data in stream_events:
            event_id = (
                raw_event_id.decode()
                if isinstance(raw_event_id, bytes)
                else str(raw_event_id)
            )
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            event_ids.append(event_id)
            events.append((event_id, self._decode_event_data(raw_event_data)))
