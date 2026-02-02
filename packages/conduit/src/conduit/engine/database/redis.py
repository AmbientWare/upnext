"""Redis storage backend for job history."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from conduit.engine.database.base import JobFilter, JobRecord
from conduit.engine.status import StatusEvent

logger = logging.getLogger(__name__)


# Default TTL: 1 day
DEFAULT_TTL_SECONDS = 86400


class RedisStorage:
    """
    Redis storage backend for job history.

    Stores job records with automatic TTL expiration.
    Supports multi-process access natively.

    Key structure:
        conduit:job:{id}           - Hash with job details
        conduit:jobs:by_status:{s} - Sorted set (score = timestamp)
        conduit:jobs:by_time       - Sorted set (score = timestamp)
        conduit:jobs:by_function:{f} - Sorted set (score = timestamp)

    Example:
        client = redis.asyncio.from_url("redis://localhost:6379")
        storage = RedisStorage(client)

        await storage.record_started(job_id, function, ...)
        await storage.record_completed(job_id, result, duration_ms)

        jobs = await storage.get_jobs(JobFilter(status="failed"), limit=10)
    """

    def __init__(
        self,
        client: Any,
        key_prefix: str = "conduit",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """
        Initialize Redis storage.

        Args:
            client: Redis-compatible async client (redis.asyncio or fakeredis)
            key_prefix: Prefix for all keys
            ttl_seconds: TTL for job records (default: 1 day)
        """
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self._client: Any = client

    @property
    def client(self) -> Any:
        """Get the Redis client."""
        if self._client is None:
            raise RuntimeError("Storage client is None.")
        return self._client

    def _job_key(self, job_id: str) -> str:
        return f"{self.key_prefix}:job:{job_id}"

    def _status_key(self, status: str) -> str:
        return f"{self.key_prefix}:jobs:by_status:{status}"

    def _function_key(self, function: str) -> str:
        return f"{self.key_prefix}:jobs:by_function:{function}"

    def _time_key(self) -> str:
        return f"{self.key_prefix}:jobs:by_time"

    async def record_started(
        self,
        job_id: str,
        function: str,
        worker_id: str,
        attempt: int,
        max_retries: int,
        kwargs: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        """Record that a job has started."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        now_ts = now.timestamp()

        job_data = {
            "id": job_id,
            "function": function,
            "status": "active",
            "created_at": now_iso,
            "started_at": now_iso,
            "attempts": str(attempt),
            "max_retries": str(max_retries),
            "worker_id": worker_id,
            "kwargs": json.dumps(kwargs),
            "metadata": json.dumps(metadata),
        }

        pipe = self.client.pipeline()
        pipe.hset(self._job_key(job_id), mapping=job_data)
        pipe.expire(self._job_key(job_id), self.ttl_seconds)
        pipe.zadd(self._status_key("active"), {job_id: now_ts})
        pipe.expire(self._status_key("active"), self.ttl_seconds)
        pipe.zadd(self._function_key(function), {job_id: now_ts})
        pipe.expire(self._function_key(function), self.ttl_seconds)
        pipe.zadd(self._time_key(), {job_id: now_ts})
        pipe.expire(self._time_key(), self.ttl_seconds)
        await pipe.execute()

    async def record_completed(
        self,
        job_id: str,
        result: Any,
        duration_ms: int,
    ) -> None:
        """Record that a job completed successfully."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        now_ts = now.timestamp()

        # Get current status to remove from old index
        old_status = await self.client.hget(self._job_key(job_id), "status")

        pipe = self.client.pipeline()
        pipe.hset(
            self._job_key(job_id),
            mapping={
                "status": "complete",
                "completed_at": now_iso,
                "duration_ms": str(duration_ms),
                "result": json.dumps(result),
            },
        )
        pipe.expire(self._job_key(job_id), self.ttl_seconds)

        # Move between status indexes
        if old_status:
            pipe.zrem(
                self._status_key(
                    old_status.decode() if isinstance(old_status, bytes) else old_status
                ),
                job_id,
            )
        pipe.zadd(self._status_key("complete"), {job_id: now_ts})
        pipe.expire(self._status_key("complete"), self.ttl_seconds)

        await pipe.execute()

    async def record_failed(
        self,
        job_id: str,
        error: str,
        error_traceback: str | None,
        duration_ms: int,
    ) -> None:
        """Record that a job failed."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        now_ts = now.timestamp()

        old_status = await self.client.hget(self._job_key(job_id), "status")

        update = {
            "status": "failed",
            "completed_at": now_iso,
            "duration_ms": str(duration_ms),
            "error": error,
        }
        if error_traceback:
            update["error_traceback"] = error_traceback

        pipe = self.client.pipeline()
        pipe.hset(self._job_key(job_id), mapping=update)
        pipe.expire(self._job_key(job_id), self.ttl_seconds)

        if old_status:
            pipe.zrem(
                self._status_key(
                    old_status.decode() if isinstance(old_status, bytes) else old_status
                ),
                job_id,
            )
        pipe.zadd(self._status_key("failed"), {job_id: now_ts})
        pipe.expire(self._status_key("failed"), self.ttl_seconds)

        await pipe.execute()

    async def record_retrying(
        self,
        job_id: str,
        attempt: int,
        _delay: float,
    ) -> None:
        """Record that a job is being retried."""
        now_ts = datetime.now(UTC).timestamp()

        old_status = await self.client.hget(self._job_key(job_id), "status")

        pipe = self.client.pipeline()
        pipe.hset(
            self._job_key(job_id),
            mapping={"status": "retrying", "attempts": str(attempt)},
        )
        pipe.expire(self._job_key(job_id), self.ttl_seconds)

        if old_status:
            pipe.zrem(
                self._status_key(
                    old_status.decode() if isinstance(old_status, bytes) else old_status
                ),
                job_id,
            )
        pipe.zadd(self._status_key("retrying"), {job_id: now_ts})
        pipe.expire(self._status_key("retrying"), self.ttl_seconds)

        await pipe.execute()

    async def get_job(self, job_id: str) -> JobRecord | None:
        """Get a job by ID."""
        data = await self.client.hgetall(self._job_key(job_id))
        if not data:
            return None
        return self._hash_to_record(data)

    async def get_jobs(
        self,
        filter: JobFilter | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobRecord]:
        """Get jobs matching filter criteria."""
        # Determine which index to use
        if filter and filter.status:
            key = self._status_key(filter.status)
        elif filter and filter.function:
            key = self._function_key(filter.function)
        else:
            key = self._time_key()

        # Get job IDs from sorted set (newest first)
        job_ids = await self.client.zrevrange(key, offset, offset + limit - 1)

        if not job_ids:
            return []

        # Fetch all job data
        pipe = self.client.pipeline()
        for job_id in job_ids:
            jid = job_id.decode() if isinstance(job_id, bytes) else job_id
            pipe.hgetall(self._job_key(jid))

        results = await pipe.execute()

        jobs = []
        for data in results:
            if data:
                record = self._hash_to_record(data)
                # Apply additional filters
                if filter:
                    if filter.function and record.function != filter.function:
                        continue
                    if filter.status and record.status != filter.status:
                        continue
                    if filter.worker_id and record.worker_id != filter.worker_id:
                        continue
                    if filter.since and record.created_at < filter.since:
                        continue
                    if filter.until and record.created_at > filter.until:
                        continue
                jobs.append(record)

        return jobs

    async def batch_send(self, events: list[StatusEvent]) -> None:
        """Process a batch of status events."""
        for event in events:
            event_type = event.type
            job_id = event.job_id
            data = event.data

            if event_type == "job.started":
                await self.record_started(
                    job_id=job_id,
                    function=data.get("function", ""),
                    worker_id=event.worker_id,
                    attempt=data.get("attempt", 1),
                    max_retries=data.get("max_retries", 0),
                    kwargs={},
                    metadata={},
                )
            elif event_type == "job.completed":
                await self.record_completed(
                    job_id=job_id,
                    result=data.get("result"),
                    duration_ms=int(data.get("duration_ms", 0) or 0),
                )
            elif event_type == "job.failed":
                await self.record_failed(
                    job_id=job_id,
                    error=data.get("error", "Unknown error"),
                    error_traceback=data.get("traceback"),
                    duration_ms=int(data.get("duration_ms", 0) or 0),
                )
            elif event_type == "job.retrying":
                await self.record_retrying(
                    job_id=job_id,
                    attempt=data.get("current_attempt", 1),
                    _delay=data.get("delay_seconds", 0),
                )

    async def get_stats(
        self,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """Get aggregate statistics."""
        stats = {
            "total": 0,
            "active": 0,
            "complete": 0,
            "failed": 0,
            "retrying": 0,
        }

        for status in ["active", "complete", "failed", "retrying"]:
            if since:
                # Count only jobs since timestamp
                count = await self.client.zcount(
                    self._status_key(status),
                    since.timestamp(),
                    "+inf",
                )
            else:
                count = await self.client.zcard(self._status_key(status))
            stats[status] = count
            stats["total"] += count

        return stats

    def _hash_to_record(self, data: dict[bytes | str, bytes | str]) -> JobRecord:
        """Convert Redis hash to JobRecord."""

        def get(key: str, default: str = "") -> str:
            val = data.get(key) or data.get(key.encode())
            if val is None:
                return default
            return val.decode() if isinstance(val, bytes) else val

        def get_int(key: str, default: int = 0) -> int:
            val = get(key)
            return int(val) if val else default

        def get_json(key: str) -> Any:
            val = get(key)
            return json.loads(val) if val else None

        created_at_str = get("created_at")
        started_at_str = get("started_at")
        completed_at_str = get("completed_at")

        return JobRecord(
            id=get("id"),
            function=get("function"),
            status=get("status"),
            created_at=datetime.fromisoformat(created_at_str)
            if created_at_str
            else datetime.now(UTC),
            started_at=datetime.fromisoformat(started_at_str)
            if started_at_str
            else None,
            completed_at=datetime.fromisoformat(completed_at_str)
            if completed_at_str
            else None,
            duration_ms=get_int("duration_ms"),
            attempts=get_int("attempts", 1),
            max_retries=get_int("max_retries"),
            worker_id=get("worker_id") or None,
            result=get_json("result"),
            error=get("error") or None,
            error_traceback=get("error_traceback") or None,
            kwargs=get_json("kwargs") or {},
            metadata=get_json("metadata") or {},
        )
