"""Queue mutation helpers for jobs routes."""

from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, cast

from redis.asyncio import Redis
from shared.domain.jobs import Job, JobStatus
from shared.keys import (
    QUEUE_CONSUMER_GROUP,
    function_dedup_key,
    function_scheduled_key,
    function_stream_key,
    job_cancelled_key,
    job_index_key,
    job_key,
    job_match_pattern,
    job_status_channel,
)
from shared.queue_mutations import (
    delete_stream_entries_for_job as _shared_delete_stream_entries_for_job,
)
from shared.queue_mutations import (
    prepare_job_for_manual_retry,
)

from server.config import get_settings


class DuplicateIdempotencyKeyError(RuntimeError):
    """Raised when retrying a job whose idempotency key is already active."""

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(idempotency_key)
        self.idempotency_key = idempotency_key


@dataclass(frozen=True)
class CancelMutationResult:
    cancelled: bool
    deleted_stream_entries: int = 0


class _QueuePipeline(Protocol):
    async def __aenter__(self) -> "_QueuePipeline": ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...
    def setex(self, key: str, seconds: int, value: object) -> object: ...
    def delete(self, *keys: str) -> object: ...
    def zrem(self, key: str, *members: str) -> object: ...
    def sadd(self, key: str, *members: str) -> object: ...
    def expire(self, key: str, seconds: int) -> object: ...
    def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
    ) -> object: ...
    async def execute(self) -> list[object]: ...


class _QueueRedisClient(Protocol):
    async def get(self, key: str) -> object | None: ...
    async def exists(self, key: str) -> int: ...
    async def delete(self, *keys: str) -> int: ...
    async def scan(
        self, cursor: int, *, match: str, count: int
    ) -> tuple[int, list[object]]: ...
    async def ttl(self, key: str) -> int: ...
    async def setex(self, key: str, seconds: int, value: object) -> object: ...
    async def set(
        self,
        key: str,
        value: object,
        *,
        ex: int | None = None,
        nx: bool | None = None,
    ) -> object: ...
    async def zrem(self, key: str, *members: str) -> int: ...
    async def srem(self, key: str, *members: str) -> int: ...
    async def publish(self, channel: str, message: str) -> int: ...
    async def xgroup_create(
        self, key: str, group: str, *, id: str, mkstream: bool = False
    ) -> object: ...
    async def sismember(self, key: str, member: str) -> bool | int: ...
    def pipeline(self, *, transaction: bool = True) -> _QueuePipeline: ...


def _decode_text(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _queue_redis(redis_client: Redis) -> _QueueRedisClient:
    return cast(_QueueRedisClient, redis_client)


async def find_job_key_by_id(redis_client: Redis, job_id: str) -> str | None:
    """Find the canonical job payload key for a job ID."""
    redis = _queue_redis(redis_client)
    index_key = job_index_key(job_id)
    indexed_job_key = await redis.get(index_key)
    if indexed_job_key:
        resolved_job_key = _decode_text(indexed_job_key)
        if await redis.exists(resolved_job_key):
            return resolved_job_key
        await redis.delete(index_key)

    cursor = 0
    match = job_match_pattern(job_id)
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=match, count=100)
        for key in keys:
            resolved_job_key = _decode_text(key)
            if await redis.exists(resolved_job_key):
                ttl = await redis.ttl(resolved_job_key)
                if ttl and ttl > 0:
                    await redis.setex(index_key, int(ttl), resolved_job_key)
                else:
                    await redis.set(index_key, resolved_job_key)
                return resolved_job_key
        if int(cursor) == 0:
            break

    return None


async def load_job(redis_client: Redis, job_id: str) -> tuple[Job | None, str | None]:
    """Load a job from active queue storage."""
    redis = _queue_redis(redis_client)
    resolved_job_key = await find_job_key_by_id(redis_client, job_id)
    if resolved_job_key is None:
        return None, None

    job_data = await redis.get(resolved_job_key)
    if not job_data:
        return None, None

    return Job.from_json(_decode_text(job_data)), resolved_job_key


async def delete_stream_entries_for_job(
    redis_client: Redis,
    stream_key: str,
    job_id: str,
    *,
    batch_size: int = 500,
    max_scan: int = 50_000,
) -> int:
    """Delete queued entries for a job ID from a stream."""
    return await _shared_delete_stream_entries_for_job(
        redis_client,
        stream_key,
        job_id,
        batch_size=batch_size,
        max_scan=max_scan,
    )


async def cancel_job(
    redis_client: Redis,
    job: Job,
    *,
    existing_job_key: str | None,
) -> CancelMutationResult:
    """Cancel a queued/running job in queue storage and return deleted stream rows."""
    redis = _queue_redis(redis_client)
    settings = get_settings()

    stream_key = function_stream_key(job.function)
    scheduled_key = function_scheduled_key(job.function)
    dedup_key = function_dedup_key(job.function)
    index_key = job_index_key(job.id)
    cancel_key = job_cancelled_key(job.id)

    job_ttl = max(1, settings.queue_job_ttl_seconds)
    marker_created = bool(
        await redis.set(
            cancel_key,
            "1",
            ex=job_ttl,
            nx=True,
        )
    )

    if not existing_job_key:
        if marker_created:
            await redis.delete(cancel_key)
        return CancelMutationResult(cancelled=False)

    current = await redis.get(existing_job_key)
    if not current:
        if marker_created:
            await redis.delete(cancel_key)
        return CancelMutationResult(cancelled=False)

    live_job = Job.from_json(_decode_text(current))
    if live_job.status.is_terminal():
        if marker_created:
            await redis.delete(cancel_key)
        return CancelMutationResult(cancelled=False)

    await redis.zrem(scheduled_key, job.id)
    deleted_from_stream = await delete_stream_entries_for_job(
        redis_client,
        stream_key,
        job.id,
    )

    await redis.delete(existing_job_key)
    await redis.delete(index_key)
    if job.key:
        await redis.srem(dedup_key, job.key)

    await redis.publish(job_status_channel(job.id), JobStatus.CANCELLED.value)
    return CancelMutationResult(
        cancelled=True,
        deleted_stream_entries=deleted_from_stream,
    )


async def _ensure_consumer_group(redis_client: Redis, stream_key: str) -> None:
    redis = _queue_redis(redis_client)
    try:
        await redis.xgroup_create(
            stream_key,
            QUEUE_CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def manual_retry(redis_client: Redis, job: Job) -> None:
    """Requeue a failed/cancelled job for operator-initiated retry."""
    redis = _queue_redis(redis_client)
    if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
        raise ValueError(
            f"Job {job.id} cannot be retried from status '{job.status.value}'"
        )

    settings = get_settings()

    prepare_job_for_manual_retry(job)

    stream_key = function_stream_key(job.function)
    scheduled_key = function_scheduled_key(job.function)
    dedup_key = function_dedup_key(job.function)
    stored_job_key = job_key(job.function, job.id)
    index_key = job_index_key(job.id)

    if job.key and await redis.sismember(dedup_key, job.key):
        raise DuplicateIdempotencyKeyError(job.key)

    await _ensure_consumer_group(redis_client, stream_key)

    payload_json = job.to_json()
    payload = {"job_id": job.id, "function": job.function, "data": payload_json}
    async with redis.pipeline(transaction=True) as pipe:
        pipe.setex(
            stored_job_key,
            max(1, settings.queue_job_ttl_seconds),
            payload_json,
        )
        pipe.setex(
            index_key,
            max(1, settings.queue_job_ttl_seconds),
            stored_job_key,
        )
        pipe.delete(job_cancelled_key(job.id))
        pipe.zrem(scheduled_key, job.id)
        if job.key:
            pipe.sadd(dedup_key, job.key)
            pipe.expire(dedup_key, max(1, settings.queue_job_ttl_seconds))
        if settings.queue_stream_maxlen > 0:
            pipe.xadd(stream_key, payload, maxlen=settings.queue_stream_maxlen)
        else:
            pipe.xadd(stream_key, payload)
        await pipe.execute()
