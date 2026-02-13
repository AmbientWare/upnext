"""Queue metrics service - reads queue depth from Redis streams."""

import json
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shared.contracts import DispatchReasonMetrics
from shared.domain import Job
from shared.keys import (
    QUEUE_CONSUMER_GROUP,
    dispatch_reasons_pattern,
    dispatch_reasons_prefix,
    function_scheduled_pattern,
    function_stream_pattern,
    job_key,
    worker_instance_pattern,
)

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


class _RedisPendingRangeClient(Protocol):
    async def xpending_range(
        self,
        stream_key: str | bytes,
        group_name: str,
        min_id: str,
        max_id: str,
        count: int,
    ) -> object: ...


class _GroupInfo(BaseModel):
    """Typed XINFO GROUPS payload subset used by queue metrics."""

    model_config = ConfigDict(extra="ignore")

    name: str
    lag: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)


class _WorkerHeartbeat(BaseModel):
    """Typed worker heartbeat payload subset used by queue metrics."""

    model_config = ConfigDict(extra="ignore")

    active_jobs: int = Field(default=0, ge=0)
    concurrency: int = Field(default=0, ge=0)


class _DispatchReasonCounts(BaseModel):
    """Typed dispatch-reason hash payload."""

    model_config = ConfigDict(extra="ignore")

    paused: int = Field(default=0, ge=0)
    rate_limited: int = Field(default=0, ge=0)
    no_capacity: int = Field(default=0, ge=0)
    cancelled: int = Field(default=0, ge=0)
    retrying: int = Field(default=0, ge=0)


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


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _normalize_mapping(row: object) -> dict[str, object] | None:
    if not isinstance(row, Mapping):
        return None

    normalized: dict[str, object] = {}
    for raw_key, raw_value in row.items():
        key = _decode_text(raw_key)
        if isinstance(raw_value, bytes):
            normalized[key] = _decode_text(raw_value)
        else:
            normalized[key] = raw_value
    return normalized


def _parse_group_info(row: object) -> _GroupInfo | None:
    normalized = _normalize_mapping(row)
    if normalized is None:
        return None
    try:
        return _GroupInfo.model_validate(normalized)
    except ValidationError:
        return None


def _parse_worker_heartbeat(raw_data: object) -> _WorkerHeartbeat | None:
    if not raw_data:
        return None

    payload_text = _decode_text(raw_data)
    try:
        payload = json.loads(payload_text)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        return _WorkerHeartbeat.model_validate(payload)
    except ValidationError:
        return None


def _parse_dispatch_reason_counts(raw_counts: object) -> _DispatchReasonCounts | None:
    normalized = _normalize_mapping(raw_counts)
    if normalized is None:
        return None
    try:
        return _DispatchReasonCounts.model_validate(normalized)
    except ValidationError:
        return None


def _decode_pending_message_id(row: object) -> str | None:
    if isinstance(row, dict):
        message_id = row.get("message_id")
        if isinstance(message_id, bytes):
            return message_id.decode()
        if isinstance(message_id, str):
            return message_id
        return None
    if isinstance(row, (list, tuple)) and row:
        message_id = row[0]
        if isinstance(message_id, bytes):
            return message_id.decode()
        if isinstance(message_id, str):
            return message_id
    return None


async def _pending_ids_for_stream(
    redis_client: _RedisPendingRangeClient,
    stream_key: str | bytes,
    *,
    limit: int = 500,
) -> set[str]:
    """Return pending (claimed) message IDs so oldest-queued excludes claimed jobs."""
    try:
        rows = await redis_client.xpending_range(
            stream_key,
            QUEUE_CONSUMER_GROUP,
            "-",
            "+",
            limit,
        )
    except Exception:
        return set()

    pending_ids: set[str] = set()
    for row in rows:  # type: ignore[misc]
        msg_id = _decode_pending_message_id(row)
        if msg_id:
            pending_ids.add(msg_id)
    return pending_ids


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
        stream_pattern = function_stream_pattern()

        waiting = 0
        claimed = 0
        async for stream_key in r.scan_iter(match=stream_pattern, count=100):
            try:
                groups = await r.xinfo_groups(stream_key)
            except Exception:
                continue

            for row in groups:
                group = _parse_group_info(row)
                if group is None or group.name != QUEUE_CONSUMER_GROUP:
                    continue
                waiting += group.lag
                claimed += group.pending
                break

        running = 0
        capacity = 0
        async for worker_key in r.scan_iter(match=worker_instance_pattern(), count=100):
            heartbeat = _parse_worker_heartbeat(await r.get(worker_key))
            if heartbeat is None:
                continue
            running += heartbeat.active_jobs
            capacity += heartbeat.concurrency

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


def _decode_map_value(row: Mapping[str | bytes, object], key: str) -> object | None:
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
        stream_pattern = function_stream_pattern()

        async for stream_key in r.scan_iter(match=stream_pattern, count=100):
            stream_name = _decode_text(stream_key)
            function = _function_from_stream_key(stream_name)
            if function is None:
                continue

            waiting = 0
            claimed = 0
            try:
                groups = await r.xinfo_groups(stream_key)
            except Exception:
                groups = []

            for row in groups:
                group = _parse_group_info(row)
                if group is None or group.name != QUEUE_CONSUMER_GROUP:
                    continue
                waiting = group.lag
                claimed = group.pending
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

        async for stream_key in r.scan_iter(match=function_stream_pattern(), count=100):
            stream_name = _decode_text(stream_key)
            function = _function_from_stream_key(stream_name)
            if function is None:
                continue
            pending_ids = await _pending_ids_for_stream(r, stream_key)  # type: ignore[arg-type]
            try:
                events = await r.xrange(stream_key, min="-", max="+", count=50)
            except Exception:
                events = []
            if not events:
                continue

            selected: tuple[object, Mapping[str | bytes, object]] | None = None
            for message_id_raw, payload in events:
                message_id = _decode_text(message_id_raw)
                if message_id in pending_ids:
                    continue
                selected = (message_id_raw, payload)
                break
            if selected is None:
                continue

            message_id_raw, payload = selected
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
            match=function_scheduled_pattern(),
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
                job_raw = await r.get(job_key(function, job_id))
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


def _parse_dispatch_reason_key(key: str) -> str | None:
    prefix = f"{dispatch_reasons_prefix()}:"
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
            match=dispatch_reasons_pattern(),
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
            parsed_counts = _parse_dispatch_reason_counts(raw_counts)
            if parsed_counts is None:
                continue

            out[function] = DispatchReasonMetrics(
                paused=parsed_counts.paused,
                rate_limited=parsed_counts.rate_limited,
                no_capacity=parsed_counts.no_capacity,
                cancelled=parsed_counts.cancelled,
                retrying=parsed_counts.retrying,
            )

        return out
    except Exception as e:
        logger.debug("Could not get function dispatch reason stats: %s", e)
        return {}
