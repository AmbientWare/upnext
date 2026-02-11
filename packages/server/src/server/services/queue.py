"""Queue metrics service - reads queue depth from Redis streams."""

import json
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared.models import Job
from shared.queue import (
    QUEUE_CONSUMER_GROUP,
    QUEUE_DISPATCH_REASONS_PREFIX,
    QUEUE_KEY_PREFIX,
)
from shared.schemas import DispatchReason, DispatchReasonMetrics
from shared.workers import WORKER_INSTANCE_KEY_PREFIX

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueDepthStats:
    """Aggregate queue depth metrics."""

    running: int
    waiting: int
    claimed: int
    capacity: int
    total: int


@dataclass(frozen=True)
class FunctionQueueDepthStats:
    """Per-function queue depth metrics."""

    function: str
    waiting: int
    claimed: int

    @property
    def backlog(self) -> int:
        return self.waiting + self.claimed


@dataclass(frozen=True)
class QueuedJobSnapshot:
    """Oldest queued-job probe used for runbook dashboard panels."""

    id: str
    function: str
    function_name: str
    queued_at: datetime
    age_seconds: float
    source: str


def _coerce_int(value: object) -> int:
    """Convert Redis mixed int/str/bytes payloads to int safely."""
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


async def get_queue_depth_stats() -> QueueDepthStats:
    """
    Get total queue depth directly from Redis.

    - waiting: sum of stream consumer-group lag (not yet claimed)
    - claimed: sum of consumer-group pending (claimed, not acked)
    - running: sum of worker heartbeat active_jobs (currently executing)
    - capacity: sum of worker heartbeat concurrency
    - total: running + waiting
    """
    try:
        r = await get_redis()
        stream_pattern = f"{QUEUE_KEY_PREFIX}:fn:*:stream"

        waiting = 0
        claimed = 0
        async for stream_key in r.scan_iter(match=stream_pattern, count=100):
            try:
                groups = await r.xinfo_groups(stream_key)
            except Exception:
                continue

            for group in groups:
                if not isinstance(group, dict):
                    continue
                name = group.get("name", group.get(b"name"))
                if isinstance(name, bytes):
                    name = name.decode()
                if name != QUEUE_CONSUMER_GROUP:
                    continue

                lag = _coerce_int(group.get("lag", group.get(b"lag", 0)))
                pending = _coerce_int(group.get("pending", group.get(b"pending", 0)))
                waiting += max(lag, 0)
                claimed += max(pending, 0)
                break

        running = 0
        capacity = 0
        async for worker_key in r.scan_iter(
            match=f"{WORKER_INSTANCE_KEY_PREFIX}:*", count=100
        ):
            data = await r.get(worker_key)
            if not data:
                continue
            try:
                payload = json.loads(data)
            except Exception:
                continue
            running += max(_coerce_int(payload.get("active_jobs", 0)), 0)
            capacity += max(_coerce_int(payload.get("concurrency", 0)), 0)

        return QueueDepthStats(
            running=running,
            waiting=waiting,
            claimed=claimed,
            capacity=capacity,
            total=running + waiting,
        )
    except Exception as e:
        logger.debug("Could not get queue depth stats: %s", e)
        return QueueDepthStats(running=0, waiting=0, claimed=0, capacity=0, total=0)


def _function_from_stream_key(stream_key: str) -> str | None:
    parts = stream_key.split(":")
    try:
        fn_idx = parts.index("fn")
    except ValueError:
        return None
    if fn_idx + 2 >= len(parts):
        return None
    function = parts[fn_idx + 1]
    suffix = parts[fn_idx + 2]
    if suffix != "stream" or not function:
        return None
    return function


def _function_from_scheduled_key(scheduled_key: str) -> str | None:
    parts = scheduled_key.split(":")
    try:
        fn_idx = parts.index("fn")
    except ValueError:
        return None
    if fn_idx + 2 >= len(parts):
        return None
    function = parts[fn_idx + 1]
    suffix = parts[fn_idx + 2]
    if suffix != "scheduled" or not function:
        return None
    return function


def _decode_map_value(row: dict[Any, Any], key: str) -> Any:
    return row.get(key, row.get(key.encode()))


def _queued_at_from_stream_id(message_id: str) -> datetime:
    try:
        ms = int(message_id.split("-", 1)[0])
    except Exception:
        return datetime.now(UTC)
    return datetime.fromtimestamp(ms / 1000, UTC)


async def get_function_queue_depth_stats() -> dict[str, FunctionQueueDepthStats]:
    """Get per-function queue lag/pending counts from Redis stream groups."""
    try:
        r = await get_redis()
        out: dict[str, FunctionQueueDepthStats] = {}
        stream_pattern = f"{QUEUE_KEY_PREFIX}:fn:*:stream"

        async for stream_key in r.scan_iter(match=stream_pattern, count=100):
            stream_name = (
                stream_key.decode()
                if isinstance(stream_key, bytes)
                else str(stream_key)
            )
            function = _function_from_stream_key(stream_name)
            if function is None:
                continue

            waiting = 0
            claimed = 0
            try:
                groups = await r.xinfo_groups(stream_key)
            except Exception:
                groups = []

            for group in groups:
                if not isinstance(group, dict):
                    continue
                name = group.get("name", group.get(b"name"))
                if isinstance(name, bytes):
                    name = name.decode()
                if name != QUEUE_CONSUMER_GROUP:
                    continue
                waiting = max(_coerce_int(group.get("lag", group.get(b"lag", 0))), 0)
                claimed = max(
                    _coerce_int(group.get("pending", group.get(b"pending", 0))),
                    0,
                )
                break

            out[function] = FunctionQueueDepthStats(
                function=function,
                waiting=waiting,
                claimed=claimed,
            )

        return out
    except Exception as e:
        logger.debug("Could not get function queue depth stats: %s", e)
        return {}


async def get_oldest_queued_jobs(limit: int = 10) -> list[QueuedJobSnapshot]:
    """Get oldest queued jobs from stream and scheduled Redis queue storage."""
    try:
        r = await get_redis()
        now = datetime.now(UTC)
        rows: list[QueuedJobSnapshot] = []

        async for stream_key in r.scan_iter(
            match=f"{QUEUE_KEY_PREFIX}:fn:*:stream", count=100
        ):
            stream_name = _decode_text(stream_key)
            function = _function_from_stream_key(stream_name)
            if function is None:
                continue
            try:
                events = await r.xrange(stream_key, min="-", max="+", count=1)
            except Exception:
                events = []
            if not events:
                continue

            message_id_raw, payload = events[0]
            message_id = _decode_text(message_id_raw)
            raw_data = _decode_map_value(payload, "data")
            queued_at = _queued_at_from_stream_id(message_id)
            job_id = _decode_map_value(payload, "job_id")
            job_function = function
            job_function_name = function
            if raw_data:
                try:
                    parsed_job = Job.from_json(_decode_text(raw_data))
                    job_id = parsed_job.id
                    job_function = parsed_job.function
                    job_function_name = parsed_job.function_name
                    if parsed_job.scheduled_at is not None:
                        queued_at = parsed_job.scheduled_at.astimezone(UTC)
                except Exception:
                    pass

            if not job_id:
                continue

            age_seconds = max(0.0, (now - queued_at).total_seconds())
            rows.append(
                QueuedJobSnapshot(
                    id=_decode_text(job_id),
                    function=job_function,
                    function_name=job_function_name,
                    queued_at=queued_at,
                    age_seconds=round(age_seconds, 3),
                    source="stream",
                )
            )

        async for scheduled_key in r.scan_iter(
            match=f"{QUEUE_KEY_PREFIX}:fn:*:scheduled",
            count=100,
        ):
            scheduled_name = _decode_text(scheduled_key)
            function = _function_from_scheduled_key(scheduled_name)
            if function is None:
                continue
            try:
                entries = await r.zrange(scheduled_key, 0, 0, withscores=True)
            except Exception:
                entries = []
            if not entries:
                continue
            member_raw, score = entries[0]
            job_id = _decode_text(member_raw)
            queued_at = datetime.fromtimestamp(float(score), UTC)
            job_function_name = function

            try:
                job_raw = await r.get(f"{QUEUE_KEY_PREFIX}:job:{function}:{job_id}")
            except Exception:
                job_raw = None
            if job_raw:
                try:
                    parsed_job = Job.from_json(_decode_text(job_raw))
                    job_function_name = parsed_job.function_name
                except Exception:
                    pass

            age_seconds = max(0.0, (now - queued_at).total_seconds())
            rows.append(
                QueuedJobSnapshot(
                    id=job_id,
                    function=function,
                    function_name=job_function_name,
                    queued_at=queued_at,
                    age_seconds=round(age_seconds, 3),
                    source="scheduled",
                )
            )

        rows.sort(key=lambda row: row.queued_at)
        return rows[: max(0, limit)]
    except Exception as e:
        logger.debug("Could not get oldest queued jobs: %s", e)
        return []


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _parse_dispatch_reason_key(key: str) -> str | None:
    prefix = f"{QUEUE_DISPATCH_REASONS_PREFIX}:"
    if not key.startswith(prefix):
        return None
    function = key[len(prefix) :]
    return function or None


async def get_function_dispatch_reason_stats() -> dict[str, DispatchReasonMetrics]:
    """Get per-function dispatch reason counters from Redis hashes."""
    try:
        r = await get_redis()
        out: dict[str, DispatchReasonMetrics] = {}

        async for reason_key in r.scan_iter(
            match=f"{QUEUE_DISPATCH_REASONS_PREFIX}:*",
            count=100,
        ):
            redis_key = _decode_text(reason_key)
            function = _parse_dispatch_reason_key(redis_key)
            if function is None:
                continue

            raw_counts_or_awaitable = r.hgetall(reason_key)
            raw_counts = (
                await raw_counts_or_awaitable
                if isinstance(raw_counts_or_awaitable, Awaitable)
                else raw_counts_or_awaitable
            )
            if not isinstance(raw_counts, dict):
                continue

            values: dict[str, int] = {}
            for reason in DispatchReason:
                raw = raw_counts.get(
                    reason.value, raw_counts.get(reason.value.encode())
                )
                values[reason.value] = max(_coerce_int(raw), 0)

            out[function] = DispatchReasonMetrics(
                paused=values[DispatchReason.PAUSED.value],
                rate_limited=values[DispatchReason.RATE_LIMITED.value],
                no_capacity=values[DispatchReason.NO_CAPACITY.value],
                cancelled=values[DispatchReason.CANCELLED.value],
                retrying=values[DispatchReason.RETRYING.value],
            )

        return out
    except Exception as e:
        logger.debug("Could not get function dispatch reason stats: %s", e)
        return {}
