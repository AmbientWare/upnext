"""Redis stream subscriber for status events.

Subscribes to the conduit:status:events stream and processes events
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
from typing import Any

from shared.events import EVENTS_PUBSUB_CHANNEL, EVENTS_STREAM, SSEJobEvent

from server.services.event_processing import process_event

logger = logging.getLogger(__name__)


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
        redis_client: Any,
        config: StreamSubscriberConfig | None = None,
    ) -> None:
        self._config = config or StreamSubscriberConfig()
        self._redis = redis_client
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._group_created = False

        # Generate unique consumer ID
        if not self._config.consumer_id:
            hostname = socket.gethostname()
            pid = os.getpid()
            self._config.consumer_id = f"server-{hostname}-{pid}"

    @property
    def is_running(self) -> bool:
        """Check if the subscriber is running."""
        return self._task is not None and not self._task.done()

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
                processed = await self._process_batch()

                if consecutive_failures > 0:
                    logger.info("Stream subscriber: recovered from errors")
                consecutive_failures = 0

                # If we processed a full batch, immediately check for more
                if processed >= self._config.batch_size:
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

            # Wait before next poll if we didn't get a full batch
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._config.poll_interval
                )
            except asyncio.TimeoutError:
                pass

        # Final drain on shutdown
        logger.debug("Final drain of pending events...")
        try:
            while True:
                processed = await self._process_batch(drain=True)
                if processed == 0:
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
        block_ms = 0 if drain else int(self._config.poll_interval * 1000 / 4)

        try:
            result = await self._redis.xreadgroup(
                self._config.group,
                self._config.consumer_id,
                {self._config.stream: ">"},
                count=self._config.batch_size,
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
                        if eid in seen_event_ids:
                            continue
                        seen_event_ids.add(eid)
                        event_ids.append(eid)
                        events.append((eid, self._decode_event_data(event_data)))
        except Exception as e:
            logger.debug(f"Error reading from stream: {e}")

        # Claim stale events from dead consumers
        if not drain:
            try:
                remaining = self._config.batch_size - len(events)
                if remaining > 0:
                    claimed = await self._redis.xautoclaim(
                        self._config.stream,
                        self._config.group,
                        self._config.consumer_id,
                        min_idle_time=self._config.stale_claim_ms,
                        count=remaining,
                    )

                    if claimed and len(claimed) >= 2:
                        for event_id, event_data in claimed[1]:
                            eid = (
                                event_id.decode()
                                if isinstance(event_id, bytes)
                                else event_id
                            )
                            if eid in seen_event_ids:
                                continue
                            seen_event_ids.add(eid)
                            event_ids.append(eid)
                            events.append((eid, self._decode_event_data(event_data)))

                        if claimed[1]:
                            logger.debug(f"Claimed {len(claimed[1])} stale events")
            except Exception as e:
                logger.debug(f"Error claiming stale events: {e}")

        if not events:
            return 0

        # Keep processing order stable even when mixing fresh and reclaimed events.
        # Reclaimed events can be older than newly-read events.
        events.sort(key=lambda item: self._event_id_sort_key(item[0]))

        # Process events
        processed = 0
        errors = 0

        for event_id, data in events:
            try:
                event_type = data.get("type", "unknown")
                job_id = data.get("job_id", "")
                worker_id = data.get("worker_id", "")

                # Parse nested payload and then enforce canonical stream metadata.
                event_data: dict[str, Any] = {}
                if "data" in data:
                    try:
                        parsed = json.loads(data["data"])
                        if isinstance(parsed, dict):
                            event_data.update(parsed)
                    except (json.JSONDecodeError, TypeError):
                        pass
                event_data["job_id"] = job_id
                event_data.pop("worker_id", None)
                event_data.pop("type", None)

                await self._handle_event(event_type, event_data, worker_id)
                processed += 1
                ack_ids.append(event_id)

            except Exception as e:
                errors += 1
                logger.warning(f"Error processing event {event_id}: {e}")

        # ACK only successfully processed events.
        # Failed events stay pending and can be retried/reclaimed later.
        if ack_ids:
            try:
                await self._redis.xack(
                    self._config.stream, self._config.group, *ack_ids
                )
            except Exception as e:
                logger.warning(f"Error ACKing events: {e}")

        if processed > 0 or errors > 0:
            logger.debug(
                "Processed %s events (%s errors, %s acked, %s pending)",
                processed,
                errors,
                len(ack_ids),
                len(event_ids) - len(ack_ids),
            )

        return processed

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

    async def _handle_event(
        self,
        event_type: str,
        data: dict[str, Any],
        worker_id: str,
    ) -> None:
        """Process a single event by writing to database and publishing to SSE."""
        applied = await process_event(event_type, data, worker_id)
        if applied:
            await self._publish_event(event_type, data, worker_id)

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
            event = SSEJobEvent(type=event_type, worker_id=worker_id, **data)
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
        data: dict[bytes | str, bytes | str],
    ) -> dict[str, str]:
        """Decode bytes to strings in event data."""
        result = {}
        for k, v in data.items():
            key = k.decode() if isinstance(k, bytes) else k
            value = v.decode() if isinstance(v, bytes) else v
            result[key] = value
        return result
