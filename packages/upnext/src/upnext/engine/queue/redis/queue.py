"""Redis Streams queue implementation for UpNext.

Uses Redis Streams with consumer groups for reliable job processing:
- XADD to enqueue jobs
- XREADGROUP to dequeue (with consumer groups for load balancing)
- XACK on completion
- XAUTOCLAIM for crash recovery (no manual lease tracking needed)

Batching optimizations (via Fetcher/Finisher components):
- Background fetcher populates an internal inbox
- Background finisher flushes completions in batches via pipeline

Lua scripts for atomic operations:
- enqueue.lua: Atomic enqueue with deduplication
- finish.lua: Atomic job completion
- sweep.lua: Atomic scheduled job promotion
- retry.lua: Atomic job retry with re-enqueue
- cancel.lua: Atomic job cancellation
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis.asyncio as redis
from shared import Job, JobStatus
from shared.workers import FUNCTION_KEY_PREFIX

from upnext.engine.queue.base import BaseQueue, DuplicateJobError, QueueStats
from upnext.engine.queue.redis.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CLAIM_TIMEOUT_MS,
    DEFAULT_CONSUMER_GROUP,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_INBOX_SIZE,
    DEFAULT_JOB_TTL_SECONDS,
    DEFAULT_KEY_PREFIX,
    DEFAULT_OUTBOX_SIZE,
    DEFAULT_STREAM_MAXLEN,
    CompletedJob,
)
from upnext.engine.queue.redis.fetcher import Fetcher
from upnext.engine.queue.redis.finisher import Finisher
from upnext.engine.queue.redis.sweeper import Sweeper

SCRIPTS_DIR = Path(__file__).parent / "scripts"

logger = logging.getLogger(__name__)


class RedisQueue(BaseQueue):
    """
    Redis Streams-based queue implementation.

    Uses consumer groups for reliable, scalable job processing:
    - Each function gets its own stream: upnext:fn:{function}:stream
    - Consumer groups handle load balancing across workers
    - XAUTOCLAIM recovers jobs from crashed consumers
    - Scheduled jobs use a ZSET, swept into streams when due

    Key structure:
        upnext:fn:{function}:stream     - Stream for immediate jobs
        upnext:fn:{function}:scheduled  - ZSET for delayed jobs (score = run_at)
        upnext:fn:{function}:dedup      - SET for deduplication keys
        upnext:job:{function}:{id}      - Job data (with TTL)
        upnext:job_index:{id}           - Job ID -> job key mapping (with TTL)
        upnext:result:{job_id}          - Job result (with TTL)
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = DEFAULT_KEY_PREFIX,
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        claim_timeout_ms: int = DEFAULT_CLAIM_TIMEOUT_MS,
        job_ttl_seconds: int = DEFAULT_JOB_TTL_SECONDS,
        sweep_interval: float = 5.0,
        *,
        client: Any | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        inbox_size: int = DEFAULT_INBOX_SIZE,
        outbox_size: int = DEFAULT_OUTBOX_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._consumer_group = consumer_group
        self._claim_timeout_ms = claim_timeout_ms
        self._job_ttl_seconds = job_ttl_seconds
        self._sweep_interval = sweep_interval

        # Batching config (stored for component creation)
        self._batch_size = batch_size
        self._inbox_size = inbox_size
        self._outbox_size = outbox_size
        self._flush_interval = flush_interval

        self._consumer_id = f"consumer_{uuid.uuid4().hex[:8]}"
        self._client: Any = client
        self._initialized_streams: set[str] = set()

        # Lua script SHAs
        self._scripts_loaded = False
        self._enqueue_sha: str | None = None
        self._finish_sha: str | None = None
        self._sweep_sha: str | None = None
        self._retry_sha: str | None = None
        self._cancel_sha: str | None = None

        # Components (created on start)
        self._fetcher = None
        self._finisher = None
        self._sweeper = None

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    async def start(
        self,
        functions: list[str] | None = None,
    ) -> None:
        """Start the queue and background tasks."""
        if self._fetcher is not None:
            return  # Already started

        await self._ensure_connected()

        # Create and start components
        self._sweeper = Sweeper(self, sweep_interval=self._sweep_interval)
        await self._sweeper.start()

        self._finisher = Finisher(
            self,
            batch_size=self._batch_size,
            outbox_size=self._outbox_size,
            flush_interval=self._flush_interval,
        )
        await self._finisher.start()

        if functions:
            self._fetcher = Fetcher(
                self,
                batch_size=min(self._batch_size, self._inbox_size),
                inbox_size=self._inbox_size,
            )
            await self._fetcher.start(functions)

    async def close(self) -> None:
        """Stop background tasks and close connections."""
        if self._fetcher:
            await self._fetcher.stop()
            self._fetcher = None

        if self._finisher:
            await self._finisher.stop()
            self._finisher = None

        if self._sweeper:
            await self._sweeper.stop()
            self._sweeper = None

        if self._client:
            await self._client.aclose()
            self._client = None

    # =========================================================================
    # CONNECTION
    # =========================================================================

    async def _ensure_connected(self) -> Any:
        """Ensure Redis connection is established."""
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=False)

        if not self._scripts_loaded:
            await self._load_scripts()

        return self._client

    async def _load_scripts(self) -> None:
        """Load Lua scripts into Redis."""
        if self._scripts_loaded:
            return

        try:
            self._enqueue_sha = await self._client.script_load(
                (SCRIPTS_DIR / "enqueue.lua").read_text()
            )
            self._finish_sha = await self._client.script_load(
                (SCRIPTS_DIR / "finish.lua").read_text()
            )
            self._sweep_sha = await self._client.script_load(
                (SCRIPTS_DIR / "sweep.lua").read_text()
            )
            self._retry_sha = await self._client.script_load(
                (SCRIPTS_DIR / "retry.lua").read_text()
            )
            self._cancel_sha = await self._client.script_load(
                (SCRIPTS_DIR / "cancel.lua").read_text()
            )
            self._scripts_loaded = True
            logger.debug("Loaded Lua scripts into Redis")
        except Exception as e:
            logger.warning(f"Failed to load Lua scripts: {e}")
            self._scripts_loaded = False

    async def _ensure_consumer_group(self, stream_key: str) -> None:
        """Ensure consumer group exists for a stream."""
        if stream_key in self._initialized_streams:
            return

        client = await self._ensure_connected()
        try:
            await client.xgroup_create(
                stream_key, self._consumer_group, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        self._initialized_streams.add(stream_key)

    # =========================================================================
    # KEY HELPERS
    # =========================================================================

    def _key(self, *parts: str) -> str:
        return ":".join([self._key_prefix, *parts])

    def _stream_key(self, function: str) -> str:
        return self._key("fn", function, "stream")

    def _scheduled_key(self, function: str) -> str:
        return self._key("fn", function, "scheduled")

    def _dedup_key(self, function: str) -> str:
        return self._key("fn", function, "dedup")

    def _job_key(self, job: Job) -> str:
        return self._key("job", job.function, job.id)

    def _job_index_key(self, job_id: str) -> str:
        return self._key("job_index", job_id)

    def _result_key(self, job_id: str) -> str:
        return self._key("result", job_id)

    # =========================================================================
    # CORE - enqueue
    # =========================================================================

    async def enqueue(self, job: Job, *, delay: float = 0.0) -> str:
        """Add a job to the queue."""
        client = await self._ensure_connected()

        stream_key = self._stream_key(job.function)
        scheduled_key = self._scheduled_key(job.function)
        dedup_key = self._dedup_key(job.function)
        job_key = self._job_key(job)
        job_index_key = self._job_index_key(job.id)

        job.mark_queued()

        if delay <= 0:
            await self._ensure_consumer_group(stream_key)

        if self._enqueue_sha:
            dest_key = scheduled_key if delay > 0 else stream_key
            scheduled_time = time.time() + delay if delay > 0 else 0

            result = await client.evalsha(
                self._enqueue_sha,
                4,
                dedup_key,
                job_key,
                dest_key,
                job_index_key,
                job.key or "",
                job.to_json(),
                str(self._job_ttl_seconds),
                job.id,
                job.function,
                str(scheduled_time),
                str(DEFAULT_STREAM_MAXLEN),
            )

            result_str = result.decode() if isinstance(result, bytes) else result
            if result_str == "DUPLICATE":
                raise DuplicateJobError(job.key)
        else:
            # Fallback without Lua
            if job.key:
                if await client.sismember(dedup_key, job.key):
                    raise DuplicateJobError(job.key)
                await client.sadd(dedup_key, job.key)
                await client.expire(dedup_key, self._job_ttl_seconds)

            await client.setex(job_key, self._job_ttl_seconds, job.to_json().encode())
            await client.setex(job_index_key, self._job_ttl_seconds, job_key)

            if delay > 0:
                await client.zadd(scheduled_key, {job.id: time.time() + delay})
            else:
                await client.xadd(
                    stream_key,
                    {"job_id": job.id, "function": job.function, "data": job.to_json()},
                    maxlen=DEFAULT_STREAM_MAXLEN,
                    approximate=True,
                )

        return job.id

    # =========================================================================
    # CORE - dequeue
    # =========================================================================

    async def dequeue(
        self, functions: list[str], *, timeout: float = 5.0
    ) -> Job | None:
        """Get next job from the queue."""
        # If fetcher is running, pull from inbox
        if self._fetcher is not None:
            try:
                async with asyncio.timeout(timeout):
                    return await self._fetcher.inbox.get()
            except TimeoutError:
                return None

        # Fallback: direct dequeue
        return await self._dequeue_direct(functions, timeout=timeout)

    async def _dequeue_direct(
        self,
        functions: list[str],
        *,
        timeout: float = 5.0,
    ) -> Job | None:
        """Get next job directly from Redis (no batching)."""
        client = await self._ensure_connected()

        if not functions:
            return None

        deadline = time.time() + timeout
        stream_keys = {self._stream_key(fn): fn for fn in functions}

        for stream_key in stream_keys:
            await self._ensure_consumer_group(stream_key)

        while time.time() < deadline:
            remaining_ms = int((deadline - time.time()) * 1000)
            if remaining_ms <= 0:
                break

            try:
                result = await client.xreadgroup(
                    groupname=self._consumer_group,
                    consumername=self._consumer_id,
                    streams={sk: ">" for sk in stream_keys},
                    count=1,
                    block=min(remaining_ms, 10),
                )

                if result:
                    for stream_key, messages in result:
                        sk = (
                            stream_key.decode()
                            if isinstance(stream_key, bytes)
                            else stream_key
                        )
                        for msg_id, msg_data in messages:
                            job = await self._process_message(sk, msg_id, msg_data)
                            if job:
                                return job

            except redis.ResponseError as e:
                if "NOGROUP" in str(e):
                    for stream_key in stream_keys:
                        await self._ensure_consumer_group(stream_key)
                else:
                    raise

        # Try autoclaim at timeout
        for stream_key in stream_keys:
            claimed = await self._try_autoclaim(stream_key, count=1)
            if claimed:
                return claimed[0]

        return None

    async def _dequeue_batch(
        self, functions: list[str], *, count: int = 1, timeout: float = 5.0
    ) -> list[Job]:
        """Get multiple jobs at once (used by Fetcher)."""
        client = await self._ensure_connected()

        if not functions:
            return []

        deadline = time.time() + timeout
        stream_keys = {self._stream_key(fn): fn for fn in functions}

        for stream_key in stream_keys:
            await self._ensure_consumer_group(stream_key)

        jobs: list[Job] = []

        # Try autoclaim first — recover stale jobs at full batch speed
        for stream_key in stream_keys:
            remaining = count - len(jobs)
            if remaining <= 0:
                break
            claimed = await self._try_autoclaim(stream_key, count=remaining)
            jobs.extend(claimed)

        if len(jobs) >= count:
            return jobs

        # Then read new messages
        while time.time() < deadline and len(jobs) < count:
            remaining_ms = int((deadline - time.time()) * 1000)
            if remaining_ms <= 0:
                break

            try:
                result = await client.xreadgroup(
                    groupname=self._consumer_group,
                    consumername=self._consumer_id,
                    streams={sk: ">" for sk in stream_keys},
                    count=count - len(jobs),
                    block=min(remaining_ms, 10),
                )

                if result:
                    for stream_key, messages in result:
                        sk = (
                            stream_key.decode()
                            if isinstance(stream_key, bytes)
                            else stream_key
                        )
                        for msg_id, msg_data in messages:
                            job = await self._process_message(sk, msg_id, msg_data)
                            if job:
                                jobs.append(job)
                                if len(jobs) >= count:
                                    return jobs

            except redis.ResponseError as e:
                if "NOGROUP" in str(e):
                    for stream_key in stream_keys:
                        await self._ensure_consumer_group(stream_key)
                else:
                    raise

            if jobs:
                return jobs

        return jobs

    async def _try_autoclaim(self, stream_key: str, *, count: int = 1) -> list[Job]:
        """Try to claim stale messages from dead consumers."""
        client = await self._ensure_connected()
        jobs: list[Job] = []

        try:
            result = await client.xautoclaim(
                stream_key,
                self._consumer_group,
                self._consumer_id,
                min_idle_time=self._claim_timeout_ms,
                start_id="0-0",
                count=count,
            )

            if result and len(result) >= 2:
                messages = result[1]
                for msg_id, msg_data in messages:
                    job = await self._process_message(stream_key, msg_id, msg_data)
                    if job:
                        jobs.append(job)

                if jobs:
                    func_name = stream_key.split(":")[-1]
                    logger.info(
                        f"Recovered {len(jobs)} stale job(s) for function '{func_name}'"
                    )

        except redis.ResponseError as e:
            logger.warning(f"XAUTOCLAIM failed on {stream_key}: {e}")

        return jobs

    async def _process_message(
        self,
        stream_key: str,
        msg_id: bytes | str,
        msg_data: dict[bytes | str, bytes | str],
    ) -> Job | None:
        """Process a stream message and return the job."""
        client = await self._ensure_connected()
        msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id

        # Try to get job data from stream message (fast path)
        job_data_raw = msg_data.get(b"data") or msg_data.get("data")
        if job_data_raw:
            job_str = (
                job_data_raw.decode()
                if isinstance(job_data_raw, bytes)
                else job_data_raw
            )
            job = Job.from_json(job_str)
        else:
            # Fallback for old messages
            job_id_raw = msg_data.get(b"job_id") or msg_data.get("job_id")
            if not job_id_raw:
                await client.xack(stream_key, self._consumer_group, msg_id_str)
                return None

            job_id = (
                job_id_raw.decode() if isinstance(job_id_raw, bytes) else job_id_raw
            )
            function_raw = msg_data.get(b"function") or msg_data.get("function")
            function = (
                function_raw.decode()
                if isinstance(function_raw, bytes)
                else function_raw or "unknown"
            )

            job_key = self._key("job", function, job_id)
            job_data = await client.get(job_key)
            if not job_data:
                await client.xack(stream_key, self._consumer_group, msg_id_str)
                return None

            job_str = job_data.decode() if isinstance(job_data, bytes) else job_data
            job = Job.from_json(job_str)

        # Store stream info for later ACK
        job.metadata = job.metadata or {}
        job.metadata["_stream_msg_id"] = msg_id_str
        job.metadata["_stream_key"] = stream_key

        job.status = JobStatus.ACTIVE
        job.started_at = datetime.now(UTC)

        return job

    # =========================================================================
    # CORE - finish
    # =========================================================================

    async def finish(
        self,
        job: Job,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Mark job as finished."""
        if self._finisher is not None:
            await self._finisher.put(
                CompletedJob(job=job, status=status, result=result, error=error)
            )
            return

        await self._finish_direct(job, status, result, error)

    async def _finish_direct(
        self,
        job: Job,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Mark job as finished immediately (no batching)."""
        client = await self._ensure_connected()

        msg_id = job.metadata.get("_stream_msg_id") if job.metadata else None
        stream_key = job.metadata.get("_stream_key") if job.metadata else None
        if not stream_key:
            stream_key = self._stream_key(job.function)

        job.status = status
        job.completed_at = datetime.now(UTC)
        job.result = result
        job.error = error

        result_key = self._result_key(job.id)
        job_key = self._job_key(job)
        job_index_key = self._job_index_key(job.id)
        dedup_key = self._dedup_key(job.function)
        pubsub_channel = f"upnext:job:{job.id}"

        if self._finish_sha:
            await client.evalsha(
                self._finish_sha,
                6,
                stream_key,
                result_key,
                job_key,
                job_index_key,
                dedup_key,
                pubsub_channel,
                self._consumer_group,
                msg_id or "",
                job.to_json(),
                "3600",
                job.key or "",
                status.value,
            )
        else:
            if msg_id:
                await client.xack(stream_key, self._consumer_group, msg_id)
            await client.setex(result_key, 3600, job.to_json().encode())
            await client.delete(job_key)
            await client.delete(job_index_key)
            if job.key:
                await client.srem(dedup_key, job.key)
            await client.publish(pubsub_channel, status.value)

    # =========================================================================
    # CORE - retry, cancel, get_job
    # =========================================================================

    async def retry(self, job: Job, delay: float) -> None:
        """Reschedule job for retry."""
        client = await self._ensure_connected()

        msg_id = job.metadata.get("_stream_msg_id") if job.metadata else None
        old_stream_key = job.metadata.get("_stream_key") if job.metadata else None

        # Clear stream metadata before re-enqueue
        if job.metadata:
            job.metadata.pop("_stream_msg_id", None)
            job.metadata.pop("_stream_key", None)

        job.mark_queued("Re-queued for retry")

        job_key = self._job_key(job)
        job_index_key = self._job_index_key(job.id)
        dest_key = (
            self._scheduled_key(job.function)
            if delay > 0
            else self._stream_key(job.function)
        )

        # Ensure consumer group exists for immediate retry
        if delay <= 0:
            await self._ensure_consumer_group(dest_key)

        # Use Lua script for atomic retry if available
        if self._retry_sha and old_stream_key:
            await client.evalsha(
                self._retry_sha,
                4,  # number of keys
                old_stream_key,
                job_key,
                dest_key,
                job_index_key,
                self._consumer_group,
                msg_id or "",
                job.to_json(),
                str(self._job_ttl_seconds),
                job.id,
                job.function,
                str(delay),
                str(DEFAULT_STREAM_MAXLEN),
            )
        else:
            # Fallback without Lua
            if msg_id and old_stream_key:
                await client.xack(old_stream_key, self._consumer_group, msg_id)

            await client.setex(job_key, self._job_ttl_seconds, job.to_json().encode())
            await client.setex(job_index_key, self._job_ttl_seconds, job_key)

            if delay > 0:
                await client.zadd(dest_key, {job.id: time.time() + delay})
            else:
                await client.xadd(
                    dest_key,
                    {"job_id": job.id, "function": job.function, "data": job.to_json()},
                    maxlen=DEFAULT_STREAM_MAXLEN,
                    approximate=True,
                )

    async def cancel(self, job_id: str) -> bool:
        """Cancel a job."""
        client = await self._ensure_connected()
        job_key = await self._find_job_key_by_id(job_id)
        if job_key is None:
            return False

        job_data = await client.get(job_key)
        if not job_data:
            return False

        job_str = job_data.decode() if isinstance(job_data, bytes) else job_data
        job = Job.from_json(job_str)

        if job.status.is_terminal():
            return False

        # Update job status for result storage
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)

        msg_id = job.metadata.get("_stream_msg_id") if job.metadata else None
        stream_key = self._stream_key(job.function)
        result_key = self._result_key(job.id)
        job_index_key = self._job_index_key(job.id)
        pubsub_channel = f"upnext:job:{job.id}"

        # Use Lua script for atomic cancellation if available
        if self._cancel_sha:
            await client.evalsha(
                self._cancel_sha,
                5,  # number of keys
                stream_key,
                result_key,
                job_key,
                job_index_key,
                pubsub_channel,
                self._consumer_group,
                msg_id or "",
                job.to_json(),
                "3600",
            )
        else:
            # Fallback without Lua
            if msg_id:
                await client.xack(stream_key, self._consumer_group, msg_id)
            await client.setex(result_key, 3600, job.to_json().encode())
            await client.delete(job_key)
            await client.delete(job_index_key)
            await client.publish(pubsub_channel, JobStatus.CANCELLED.value)

        return True

    async def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        client = await self._ensure_connected()

        # Check result key first
        result_key = self._result_key(job_id)
        result_data = await client.get(result_key)

        if result_data:
            result_str = (
                result_data.decode() if isinstance(result_data, bytes) else result_data
            )
            return Job.from_json(result_str)

        # Lookup active job via ID index, fallback to SCAN for backward compatibility.
        job_key = await self._find_job_key_by_id(job_id)
        if job_key is None:
            return None

        job_data = await client.get(job_key)
        if not job_data:
            return None

        job_str = job_data.decode() if isinstance(job_data, bytes) else job_data
        return Job.from_json(job_str)

    # =========================================================================
    # OPTIONAL - progress, heartbeat, metadata
    # =========================================================================

    async def update_progress(self, job_id: str, progress: float) -> None:
        job = await self.get_job(job_id)
        if job:
            job.progress = progress
            job_key = self._job_key(job)
            client = await self._ensure_connected()
            await client.setex(job_key, self._job_ttl_seconds, job.to_json().encode())

    async def heartbeat_active_jobs(self, jobs: list[Job]) -> None:
        """Reset idle time on active jobs to prevent XAUTOCLAIM from reclaiming them."""
        if not jobs:
            return

        client = await self._ensure_connected()

        # Group by stream key for efficient pipelining
        by_stream: dict[str, list[str]] = {}
        for job in jobs:
            if not job.metadata:
                continue
            stream_key = job.metadata.get("_stream_key")
            msg_id = job.metadata.get("_stream_msg_id")
            if stream_key and msg_id:
                by_stream.setdefault(stream_key, []).append(msg_id)

        for stream_key, msg_ids in by_stream.items():
            try:
                await client.xclaim(
                    stream_key,
                    self._consumer_group,
                    self._consumer_id,
                    min_idle_time=0,
                    message_ids=msg_ids,
                )
            except redis.ResponseError as e:
                logger.warning(f"Heartbeat XCLAIM failed on {stream_key}: {e}")

    async def update_job_metadata(self, job_id: str, metadata: dict[str, Any]) -> None:
        client = await self._ensure_connected()
        if not metadata:
            return

        job_key = await self._find_job_key_by_id(job_id)
        if job_key is None:
            return

        job_data = await client.get(job_key)
        if not job_data:
            return

        job = Job.from_json(
            job_data.decode() if isinstance(job_data, bytes) else job_data
        )
        job.metadata = job.metadata or {}
        job.metadata.update(metadata)

        ttl = await client.ttl(job_key)
        serialized = job.to_json()
        if ttl and ttl > 0:
            await client.setex(job_key, int(ttl), serialized)
        else:
            await client.set(job_key, serialized)

    async def _find_job_key_by_id(self, job_id: str) -> str | None:
        """Find stored job key for a job ID using index first, SCAN as fallback."""
        client = await self._ensure_connected()
        index_key = self._job_index_key(job_id)

        indexed_job_key = await client.get(index_key)
        if indexed_job_key:
            job_key = (
                indexed_job_key.decode()
                if isinstance(indexed_job_key, bytes)
                else indexed_job_key
            )
            if await client.exists(job_key):
                return job_key
            # Stale index entry — clear and fall back to scan.
            await client.delete(index_key)

        cursor = 0
        match = f"{self._key_prefix}:job:*:{job_id}"
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=match, count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                if await client.exists(key_str):
                    ttl = await client.ttl(key_str)
                    if ttl and ttl > 0:
                        await client.setex(index_key, int(ttl), key_str)
                    else:
                        await client.set(index_key, key_str)
                    return key_str
            if cursor == 0:
                break
        return None

    # =========================================================================
    # OPTIONAL - stats
    # =========================================================================

    async def get_queue_stats(self, function: str) -> QueueStats:
        client = await self._ensure_connected()

        stream_key = self._stream_key(function)
        scheduled_key = self._scheduled_key(function)

        queued_count = 0
        active_count = 0
        try:
            groups = await client.xinfo_groups(stream_key)
            for group in groups:
                if isinstance(group, dict):
                    name = group.get("name", group.get(b"name", b""))
                    if isinstance(name, bytes):
                        name = name.decode()
                    if name == self._consumer_group:
                        lag = group.get("lag", group.get(b"lag", 0))
                        pending = group.get("pending", group.get(b"pending", 0))
                        if isinstance(lag, bytes):
                            lag = int(lag)
                        if isinstance(pending, bytes):
                            pending = int(pending)
                        queued_count = lag
                        active_count = pending
                        break
        except redis.ResponseError:
            pass

        scheduled_count = await client.zcard(scheduled_key)

        return QueueStats(
            queued=queued_count, active=active_count, scheduled=scheduled_count
        )

    async def subscribe_job(self, job_id: str, timeout: float | None = None) -> str:
        client = await self._ensure_connected()

        job = await self.get_job(job_id)
        if job and job.status.is_terminal():
            return job.status.value

        pubsub = client.pubsub()
        await pubsub.subscribe(f"upnext:job:{job_id}")

        try:
            deadline = None if timeout is None else time.time() + timeout

            while True:
                if deadline is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break

                    async with asyncio.timeout(remaining):
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=remaining
                        )
                else:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )

                if message and message["type"] == "message":
                    status = message["data"]
                    if isinstance(status, bytes):
                        return status.decode()
                    return str(status)

            raise TimeoutError(f"Timeout waiting for job {job_id}")

        finally:
            await pubsub.unsubscribe(f"upnext:job:{job_id}")
            await pubsub.close()

    async def publish_event(self, event_name: str, data: dict[str, Any]) -> None:
        client = await self._ensure_connected()
        channel = self._key("events", event_name)
        await client.publish(channel, json.dumps(data))

    async def stats(self) -> dict[str, int]:
        client = await self._ensure_connected()

        total_queued = 0
        total_active = 0
        total_scheduled = 0

        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor=cursor, match=f"{self._key_prefix}:fn:*:stream", count=100
            )

            for stream_key in keys:
                key_str = (
                    stream_key.decode() if isinstance(stream_key, bytes) else stream_key
                )
                try:
                    groups = await client.xinfo_groups(key_str)
                    for group in groups:
                        if isinstance(group, dict):
                            name = group.get("name", group.get(b"name", b""))
                            if isinstance(name, bytes):
                                name = name.decode()
                            if name == self._consumer_group:
                                lag = group.get("lag", group.get(b"lag", 0))
                                pending = group.get("pending", group.get(b"pending", 0))
                                if isinstance(lag, bytes):
                                    lag = int(lag)
                                if isinstance(pending, bytes):
                                    pending = int(pending)
                                total_queued += lag
                                total_active += pending
                                break
                except redis.ResponseError:
                    pass

            if cursor == 0:
                break

        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor=cursor, match=f"{self._key_prefix}:fn:*:scheduled", count=100
            )

            for key in keys:
                count = await client.zcard(key)
                total_scheduled += count

            if cursor == 0:
                break

        return {
            "queued": max(0, total_queued),
            "active": total_active,
            "scheduled": total_scheduled,
        }

    async def get_queued_jobs(self, function: str, *, limit: int = 100) -> list[Job]:
        client = await self._ensure_connected()
        stream_key = self._stream_key(function)

        try:
            result = await client.xrange(stream_key, count=limit)
        except redis.ResponseError:
            return []

        jobs: list[Job] = []
        for _msg_id, msg_data in result:
            job_id = msg_data.get(b"job_id", msg_data.get("job_id"))
            if isinstance(job_id, bytes):
                job_id = job_id.decode()

            if job_id:
                job = await self.get_job(job_id)
                if job:
                    jobs.append(job)

        return jobs

    # =========================================================================
    # STREAM OPERATIONS (for user-facing stream processing)
    # =========================================================================

    async def publish_to_stream(
        self, stream_name: str, data: dict[str, Any], *, max_len: int | None = None
    ) -> str:
        client = await self._ensure_connected()
        stream_key = self._key("stream", stream_name)

        flat_data: dict[str, str | bytes] = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                flat_data[key] = json.dumps(value)
            else:
                flat_data[key] = str(value)

        if max_len is not None:
            event_id = await client.xadd(
                stream_key, flat_data, maxlen=max_len, approximate=True
            )
        else:
            event_id = await client.xadd(stream_key, flat_data)

        return event_id.decode() if isinstance(event_id, bytes) else str(event_id)

    async def read_stream(
        self,
        stream_name: str,
        *,
        group: str,
        consumer: str,
        count: int = 100,
        block: int = 1000,
        start_id: str = ">",
    ) -> list[tuple[str, dict[str, Any]]]:
        client = await self._ensure_connected()
        stream_key = self._key("stream", stream_name)

        try:
            result = await client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream_key: start_id},
                count=count,
                block=block if block > 0 else None,
            )
        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                return []
            raise

        if not result:
            return []

        events: list[tuple[str, dict[str, Any]]] = []

        for _stream_key, messages in result:
            for msg_id, msg_data in messages:
                event_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

                decoded_data: dict[str, Any] = {}
                for key, value in msg_data.items():
                    key_str = key.decode() if isinstance(key, bytes) else str(key)
                    value_str = (
                        value.decode() if isinstance(value, bytes) else str(value)
                    )

                    try:
                        decoded_data[key_str] = json.loads(value_str)
                    except (json.JSONDecodeError, ValueError):
                        decoded_data[key_str] = value_str

                events.append((event_id, decoded_data))

        return events

    async def ack_stream(self, stream_name: str, group: str, *event_ids: str) -> int:
        if not event_ids:
            return 0

        client = await self._ensure_connected()
        stream_key = self._key("stream", stream_name)

        result = await client.xack(stream_key, group, *event_ids)
        return int(result) if result else 0

    async def create_stream_group(
        self,
        stream_name: str,
        group: str,
        *,
        start_id: str = "0",
        mkstream: bool = True,
    ) -> bool:
        client = await self._ensure_connected()
        stream_key = self._key("stream", stream_name)

        try:
            await client.xgroup_create(
                stream_key, group, id=start_id, mkstream=mkstream
            )
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                return False
            raise

    # =========================================================================
    # CRON SCHEDULING
    # =========================================================================

    def _cron_registry_key(self) -> str:
        return self._key("cron_registry")

    async def seed_cron(self, job: Job, next_run_at: float) -> bool:
        client = await self._ensure_connected()

        cron_registry = self._cron_registry_key()
        cron_key = f"cron:{job.function}"

        was_set = await client.hsetnx(cron_registry, cron_key, job.id)
        if not was_set:
            return False

        job.mark_queued("Cron job scheduled")
        job_key = self._job_key(job)
        await client.setex(job_key, self._job_ttl_seconds, job.to_json().encode())

        scheduled_key = self._scheduled_key(job.function)
        await client.zadd(scheduled_key, {job.id: next_run_at})

        await self._update_function_next_run(client, job.function, next_run_at)

        return True

    async def reschedule_cron(self, job: Job, next_run_at: float) -> str:
        client = await self._ensure_connected()

        new_job = Job(
            function=job.function,
            function_name=job.function_name,
            kwargs=job.kwargs,
            key=f"cron:{job.function}",
            schedule=job.schedule,
            timeout=job.timeout,
            metadata=dict(job.metadata or {}),
        )
        new_job.metadata.setdefault("cron", True)
        new_job.mark_queued("Cron job rescheduled")

        cron_registry = self._cron_registry_key()
        cron_key = f"cron:{job.function}"
        await client.hset(cron_registry, cron_key, new_job.id)

        job_key = self._job_key(new_job)
        await client.setex(job_key, self._job_ttl_seconds, new_job.to_json().encode())

        scheduled_key = self._scheduled_key(new_job.function)
        await client.zadd(scheduled_key, {new_job.id: next_run_at})

        await self._update_function_next_run(client, job.function, next_run_at)

        return new_job.id

    async def _update_function_next_run(
        self, client: redis.Redis, function_name: str, next_run_at: float
    ) -> None:
        """Update the function definition in Redis with the next scheduled run time."""
        func_key = f"{FUNCTION_KEY_PREFIX}:{function_name}"
        data = await client.get(func_key)
        if not data:
            return
        func_def = json.loads(data)
        func_def["next_run_at"] = datetime.fromtimestamp(next_run_at, UTC).isoformat()
        ttl = await client.ttl(func_key)
        if ttl > 0:
            await client.setex(func_key, ttl, json.dumps(func_def))
        else:
            await client.set(func_key, json.dumps(func_def))
