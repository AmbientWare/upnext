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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis.asyncio as redis
from pydantic import BaseModel
from shared import CronSource, Job, JobStatus, clone_job_source
from shared.contracts import DispatchReason, FunctionConfig, MissedRunPolicy
from shared.keys import (
    QUEUE_CONSUMER_GROUP,
    QUEUE_KEY_PREFIX,
    function_definition_key,
    function_definition_pattern,
    function_scheduled_pattern,
    function_stream_pattern,
    job_match_pattern,
    job_status_channel,
)
from shared.queue_mutations import (
    delete_stream_entries_for_job as shared_delete_stream_entries_for_job,
    prepare_job_for_manual_retry,
)

from upnext.config import ThroughputMode, get_settings
from upnext.engine.cron import calculate_next_cron_run
from upnext.engine.queue.base import (
    BaseQueue,
    DeadLetterEntry,
    DuplicateJobError,
    QueueStats,
)
from upnext.engine.queue.redis.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CLAIM_TIMEOUT_MS,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_INBOX_SIZE,
    DEFAULT_OUTBOX_SIZE,
    CompletedJob,
)
from upnext.engine.queue.redis.fetcher import Fetcher
from upnext.engine.queue.redis.finisher import Finisher
from upnext.engine.queue.redis.rate_limit import RateLimit, parse_rate_limit
from upnext.engine.queue.redis.sweeper import Sweeper

SCRIPTS_DIR = Path(__file__).parent / "scripts"

logger = logging.getLogger(__name__)


class _CronCursorRecord(BaseModel):
    function: str
    next_run_at: datetime
    last_completed_at: datetime | None = None
    updated_at: datetime


@dataclass(frozen=True)
class _StreamClaim:
    """Queue-local stream claim identity for ack/retry/cancel operations."""

    stream_key: str
    msg_id: str


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
        upnext:cron_window:{function}:{ms} - Schedule reservation key per cron window
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = QUEUE_KEY_PREFIX,
        consumer_group: str = QUEUE_CONSUMER_GROUP,
        claim_timeout_ms: int = DEFAULT_CLAIM_TIMEOUT_MS,
        job_ttl_seconds: int | None = None,
        result_ttl_seconds: int | None = None,
        sweep_interval: float = 5.0,
        *,
        client: Any | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        inbox_size: int = DEFAULT_INBOX_SIZE,
        outbox_size: int = DEFAULT_OUTBOX_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        stream_maxlen: int | None = None,
        dlq_stream_maxlen: int | None = None,
    ) -> None:
        settings = get_settings()

        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._consumer_group = consumer_group
        self._claim_timeout_ms = claim_timeout_ms
        self._job_ttl_seconds = (
            settings.queue_job_ttl_seconds
            if job_ttl_seconds is None
            else int(job_ttl_seconds)
        )
        self._result_ttl_seconds = (
            settings.queue_result_ttl_seconds
            if result_ttl_seconds is None
            else int(result_ttl_seconds)
        )
        self._sweep_interval = sweep_interval

        # Batching config (stored for component creation)
        self._batch_size = batch_size
        self._inbox_size = inbox_size
        self._outbox_size = outbox_size
        self._flush_interval = flush_interval
        self._stream_maxlen = max(
            0,
            (
                settings.default_queue_stream_maxlen()
                if stream_maxlen is None
                else int(stream_maxlen)
            ),
        )
        self._dlq_stream_maxlen = max(
            0,
            (
                settings.queue_dlq_stream_maxlen
                if dlq_stream_maxlen is None
                else int(dlq_stream_maxlen)
            ),
        )
        self._dispatch_events_stream_maxlen = max(
            0,
            int(settings.queue_dispatch_events_stream_maxlen),
        )
        self._require_lua_atomic = settings.queue_runtime_profile == ThroughputMode.SAFE

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
        self._rate_limit_sha: str | None = None

        # Function pause state cache (short-lived to avoid frequent Redis GETs).
        self._function_config_cache: dict[str, tuple[FunctionConfig | None, float]] = {}
        self._function_pause_cache: dict[str, tuple[bool, float]] = {}
        self._function_rate_limit_cache: dict[str, tuple[RateLimit | None, float]] = {}
        self._function_max_concurrency_cache: dict[str, tuple[int | None, float]] = {}
        self._function_active_count_cache: dict[str, tuple[int, float]] = {}
        self._function_group_quota_cache: dict[
            str, tuple[tuple[str | None, int | None], float]
        ] = {}
        self._group_active_count_cache: dict[str, tuple[int, float]] = {}
        self._routing_group_members_cache: tuple[dict[str, list[str]], float] | None = (
            None
        )
        self._routing_group_members_cache_ttl = 10.0
        self._dispatch_event_emit_cache: dict[tuple[str, str], float] = {}
        self._fair_dequeue_cursor = 0
        self._stream_claims: dict[str, _StreamClaim] = {}

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
            self._rate_limit_sha = await self._client.script_load(
                (SCRIPTS_DIR / "rate_limit.lua").read_text()
            )
            self._scripts_loaded = True
            logger.debug("Loaded Lua scripts into Redis")
        except Exception as e:
            logger.warning(f"Failed to load Lua scripts: {e}")
            self._scripts_loaded = False
            if self._require_lua_atomic:
                raise RuntimeError(
                    "Failed to load required Redis Lua scripts in SAFE mode. "
                    "Switch to throughput profile to allow non-atomic fallbacks."
                ) from e

    async def _evalsha_with_reload(
        self,
        script_attr: str,
        num_keys: int,
        *args: str,
    ) -> Any:
        """Run EVALSHA and recover once from Redis NOSCRIPT after restart/flush."""
        client = await self._ensure_connected()
        sha = getattr(self, script_attr, None)
        if not sha:
            raise RuntimeError(f"Lua script SHA missing for {script_attr}")

        try:
            return await client.evalsha(sha, num_keys, *args)
        except redis.ResponseError as exc:
            if "NOSCRIPT" not in str(exc):
                raise

            # Redis script cache was evicted (restart/flush); reload and retry once.
            self._scripts_loaded = False
            await self._load_scripts()

            refreshed_sha = getattr(self, script_attr, None)
            if not refreshed_sha:
                raise

            return await client.evalsha(refreshed_sha, num_keys, *args)

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

    def _dlq_stream_key(self, function: str) -> str:
        return self._key("fn", function, "dlq")

    def _dispatch_reasons_key(self, function: str) -> str:
        return self._key("dispatch_reasons", function)

    def _dispatch_events_stream_key(self) -> str:
        return self._key("dispatch_events")

    def _job_key(self, job: Job) -> str:
        return self._key("job", job.function, job.id)

    def _job_index_key(self, job_id: str) -> str:
        return self._key("job_index", job_id)

    def _result_key(self, job_id: str) -> str:
        return self._key("result", job_id)

    def _cancel_marker_key(self, job_id: str) -> str:
        return self._key("cancelled", job_id)

    def _function_def_key(self, function: str) -> str:
        return function_definition_key(function)

    def _rate_limit_key(self, function: str) -> str:
        return self._key("fn", function, "rate_limit")

    def _cron_window_token(self, run_at: float) -> str:
        # Millisecond token is stable for schedule-window dedupe keys.
        return str(int(round(run_at * 1000)))

    def _cron_window_reservation_key(self, function: str, run_at: float) -> str:
        return self._key("cron_window", function, self._cron_window_token(run_at))

    async def _reserve_cron_window(
        self,
        client: Any,
        *,
        function: str,
        run_at: float,
        job_id: str,
    ) -> tuple[bool, str | None]:
        key = self._cron_window_reservation_key(function, run_at)
        reserved = await client.set(key, job_id, nx=True, ex=self._job_ttl_seconds)
        if reserved:
            return (True, job_id)

        raw_owner = await client.get(key)
        owner = self._decode_text(raw_owner) if raw_owner else None
        if not owner:
            return (False, None)

        owner_job_key = self._key("job", function, owner)
        scheduled_score = await client.zscore(self._scheduled_key(function), owner)
        owner_exists = scheduled_score is not None or bool(
            await client.exists(owner_job_key)
        )
        if owner_exists:
            return (False, owner)

        # Reservation is stale (no owner job in scheduled or job storage); reclaim once.
        await client.delete(key)
        reclaimed = await client.set(key, job_id, nx=True, ex=self._job_ttl_seconds)
        if reclaimed:
            return (True, job_id)

        latest_owner = await client.get(key)
        return (False, self._decode_text(latest_owner) if latest_owner else None)

    def _parse_function_config(
        self,
        raw: Any,
        *,
        key_hint: str | None = None,
    ) -> FunctionConfig | None:
        if not raw:
            return None
        try:
            config = FunctionConfig.model_validate_json(self._decode_text(raw))
        except Exception:
            if key_hint:
                logger.debug("Skipping malformed function payload for key %s", key_hint)
            return None
        return config

    async def _read_function_config(self, function: str) -> FunctionConfig | None:
        now = time.time()
        cached = self._function_config_cache.get(function)
        if cached and cached[1] > now:
            return cached[0]

        client = await self._ensure_connected()
        key = self._function_def_key(function)
        raw = await client.get(key)
        config = self._parse_function_config(raw, key_hint=key)
        self._function_config_cache[function] = (config, now + 1.0)
        return config

    async def record_dispatch_reason(
        self,
        function: str,
        reason: DispatchReason,
        *,
        job_id: str | None = None,
    ) -> None:
        """Persist structured dispatch diagnostics."""
        client = await self._ensure_connected()
        counts_key = self._dispatch_reasons_key(function)
        stream_key = self._dispatch_events_stream_key()
        emit_stream_event = self._should_emit_dispatch_event(
            function=function,
            reason=reason.value,
            job_id=job_id,
        )
        try:
            async with client.pipeline(transaction=False) as pipe:
                pipe.hincrby(counts_key, reason.value, 1)
                pipe.expire(counts_key, max(1, self._job_ttl_seconds))
                if emit_stream_event:
                    payload = {
                        "function": function,
                        "reason": reason.value,
                        "job_id": job_id or "",
                        "at": datetime.now(UTC).isoformat(),
                    }
                    if self._dispatch_events_stream_maxlen > 0:
                        pipe.xadd(
                            stream_key,
                            payload,
                            maxlen=self._dispatch_events_stream_maxlen,
                            approximate=True,
                        )
                    else:
                        pipe.xadd(stream_key, payload)
                await pipe.execute()
        except Exception:
            logger.debug(
                "Failed to record dispatch reason function=%s reason=%s",
                function,
                reason.value,
            )

    def _should_emit_dispatch_event(
        self,
        *,
        function: str,
        reason: str,
        job_id: str | None,
    ) -> bool:
        """Throttle dispatch event-stream writes while preserving aggregate counters."""
        if self._dispatch_events_stream_maxlen <= 0:
            return False

        now = time.time()
        key = (function, reason)
        min_interval = 0.25 if job_id else 1.0
        previous = self._dispatch_event_emit_cache.get(key, 0.0)
        if now - previous < min_interval:
            return False
        self._dispatch_event_emit_cache[key] = now

        # Keep the in-memory throttle map bounded for long-running workers.
        if len(self._dispatch_event_emit_cache) > 10_000:
            self._dispatch_event_emit_cache.clear()
        return True

    async def _paused_state_map(self, functions: list[str]) -> dict[str, bool]:
        """Resolve paused state for functions with a small in-memory TTL cache."""
        now = time.time()
        states: dict[str, bool] = {}
        stale: list[str] = []
        for fn in functions:
            cached = self._function_pause_cache.get(fn)
            if cached and cached[1] > now:
                states[fn] = cached[0]
            else:
                stale.append(fn)

        if stale:
            client = await self._ensure_connected()
            keys = [self._function_def_key(fn) for fn in stale]
            rows = await client.mget(keys)
            for fn, key, raw in zip(stale, keys, rows, strict=False):
                paused = False
                config = self._parse_function_config(raw, key_hint=key)
                if config is not None:
                    paused = config.paused
                self._function_config_cache[fn] = (config, now + 1.0)
                states[fn] = paused
                self._function_pause_cache[fn] = (paused, now + 1.0)

        return states

    async def _function_rate_limit(self, function: str) -> RateLimit | None:
        now = time.time()
        cached = self._function_rate_limit_cache.get(function)
        if cached and cached[1] > now:
            return cached[0]

        parsed: RateLimit | None = None
        config = await self._read_function_config(function)
        if config and config.rate_limit:
            try:
                parsed = parse_rate_limit(config.rate_limit)
            except ValueError as exc:
                logger.warning(
                    "Invalid rate_limit for function '%s': %s", function, exc
                )
                parsed = None

        self._function_rate_limit_cache[function] = (parsed, now + 1.0)
        return parsed

    async def _function_max_concurrency(self, function: str) -> int | None:
        now = time.time()
        cached = self._function_max_concurrency_cache.get(function)
        if cached and cached[1] > now:
            return cached[0]

        parsed: int | None = None
        config = await self._read_function_config(function)
        if config:
            parsed = config.max_concurrency
            if parsed is not None and parsed < 1:
                logger.warning(
                    "Invalid max_concurrency for function '%s': %s",
                    function,
                    parsed,
                )
                parsed = None

        self._function_max_concurrency_cache[function] = (parsed, now + 1.0)
        return parsed

    async def _function_active_count(self, function: str) -> int:
        now = time.time()
        cached = self._function_active_count_cache.get(function)
        if cached and cached[1] > now:
            return cached[0]

        client = await self._ensure_connected()
        stream_key = self._stream_key(function)
        active = 0
        try:
            groups = await client.xinfo_groups(stream_key)
            for group in groups:
                if isinstance(group, dict):
                    name = group.get("name", group.get(b"name", b""))
                    if isinstance(name, bytes):
                        name = name.decode()
                    if name != self._consumer_group:
                        continue
                    pending = group.get("pending", group.get(b"pending", 0))
                    if isinstance(pending, bytes):
                        pending = int(pending)
                    active = int(pending)
                    break
        except redis.ResponseError:
            active = 0

        self._function_active_count_cache[function] = (active, now + 0.25)
        return active

    async def _function_group_quota(
        self,
        function: str,
    ) -> tuple[str | None, int | None]:
        now = time.time()
        cached = self._function_group_quota_cache.get(function)
        if cached and cached[1] > now:
            return cached[0]

        group: str | None = None
        limit: int | None = None
        config = await self._read_function_config(function)
        if config:
            group = config.routing_group
            limit = config.group_max_concurrency
            if group is not None:
                group = group.strip()
                if not group:
                    group = None
            if limit is not None and limit < 1:
                logger.warning(
                    "Invalid group_max_concurrency for function '%s': %s",
                    function,
                    limit,
                )
                limit = None

        result = (group, limit)
        self._function_group_quota_cache[function] = (result, now + 1.0)
        return result

    async def _group_active_count(self, group: str) -> int:
        now = time.time()
        cached = self._group_active_count_cache.get(group)
        if cached and cached[1] > now:
            return cached[0]

        members = (await self._routing_group_members()).get(group, [])

        active = 0
        for function in members:
            active += await self._function_active_count(function)

        self._group_active_count_cache[group] = (active, now + 0.25)
        return active

    async def _routing_group_members(self) -> dict[str, list[str]]:
        now = time.time()
        cached = self._routing_group_members_cache
        if cached and cached[1] > now:
            return cached[0]

        client = await self._ensure_connected()
        members: dict[str, list[str]] = {}
        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor=cursor,
                match=function_definition_pattern(),
                count=100,
            )
            rows = await client.mget(keys) if keys else []
            for raw in rows:
                config = self._parse_function_config(raw)
                if config is None or not config.routing_group:
                    continue
                members.setdefault(config.routing_group, []).append(config.key)
            if cursor == 0:
                break

        self._routing_group_members_cache = (
            members,
            now + self._routing_group_members_cache_ttl,
        )
        return members

    def _invalidate_function_active_count(self, function: str) -> None:
        self._function_active_count_cache.pop(function, None)
        self._group_active_count_cache.clear()

    def _set_stream_claim(self, job_id: str, *, stream_key: str, msg_id: str) -> None:
        self._stream_claims[job_id] = _StreamClaim(stream_key=stream_key, msg_id=msg_id)

    def _peek_stream_claim(self, job_id: str) -> _StreamClaim | None:
        return self._stream_claims.get(job_id)

    def _pop_stream_claim(self, job_id: str) -> _StreamClaim | None:
        return self._stream_claims.pop(job_id, None)

    async def _acquire_rate_limit_token(
        self,
        function: str,
        rate_limit: RateLimit,
    ) -> bool:
        client = await self._ensure_connected()
        bucket_key = self._rate_limit_key(function)
        now_ms = int(time.time() * 1000)
        ttl_ms = max(1000, int(rate_limit.window_seconds * 2000))

        if self._rate_limit_sha:
            allowed = await self._evalsha_with_reload(
                "_rate_limit_sha",
                1,
                bucket_key,
                str(now_ms),
                str(rate_limit.capacity),
                str(rate_limit.refill_per_ms),
                str(ttl_ms),
            )
            return int(allowed) == 1

        raw_tokens, raw_ts = await client.hmget(bucket_key, "tokens", "ts")
        tokens = (
            float(raw_tokens) if raw_tokens is not None else float(rate_limit.capacity)
        )
        ts = float(raw_ts) if raw_ts is not None else float(now_ms)
        if now_ms > ts:
            tokens = min(
                float(rate_limit.capacity),
                tokens + ((now_ms - ts) * rate_limit.refill_per_ms),
            )
            ts = float(now_ms)

        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0

        await client.hset(bucket_key, mapping={"tokens": tokens, "ts": ts})
        await client.pexpire(bucket_key, ttl_ms)
        return allowed

    async def is_function_paused(self, function: str) -> bool:
        states = await self._paused_state_map([function])
        return states.get(function, False)

    async def get_runnable_functions(self, functions: list[str]) -> list[str]:
        if not functions:
            return []
        states = await self._paused_state_map(functions)
        paused_functions = [fn for fn in functions if states.get(fn, False)]
        if paused_functions:
            await asyncio.gather(
                *(
                    self.record_dispatch_reason(fn, DispatchReason.PAUSED)
                    for fn in paused_functions
                )
            )

        candidates = [fn for fn in functions if not states.get(fn, False)]
        if not candidates:
            return []

        max_concurrency_values = await asyncio.gather(
            *(self._function_max_concurrency(fn) for fn in candidates)
        )

        needs_active_check = [
            fn
            for fn, max_concurrency in zip(
                candidates, max_concurrency_values, strict=False
            )
            if max_concurrency is not None
        ]
        active_counts: dict[str, int] = {}
        if needs_active_check:
            active_values = await asyncio.gather(
                *(self._function_active_count(fn) for fn in needs_active_check)
            )
            active_counts = dict(zip(needs_active_check, active_values, strict=False))

        runnable: list[str] = []
        capacity_blocked: list[str] = []
        for function, max_concurrency in zip(
            candidates, max_concurrency_values, strict=False
        ):
            if max_concurrency is None:
                runnable.append(function)
                continue
            if active_counts.get(function, 0) < max_concurrency:
                runnable.append(function)
            else:
                capacity_blocked.append(function)

        if capacity_blocked:
            await asyncio.gather(
                *(
                    self.record_dispatch_reason(fn, DispatchReason.NO_CAPACITY)
                    for fn in capacity_blocked
                )
            )

        if not runnable:
            return []

        quotas = await asyncio.gather(
            *(self._function_group_quota(fn) for fn in runnable)
        )

        functions_by_group: dict[str, list[str]] = {}
        for function, (group, group_limit) in zip(runnable, quotas, strict=False):
            if group is None or group_limit is None:
                continue
            functions_by_group.setdefault(group, []).append(function)

        group_active_counts: dict[str, int] = {}
        if functions_by_group:
            groups = list(functions_by_group)
            group_active_values = await asyncio.gather(
                *(self._group_active_count(group) for group in groups)
            )
            group_active_counts = dict(zip(groups, group_active_values, strict=False))

        filtered: list[str] = []
        group_blocked: list[str] = []
        for function, (group, group_limit) in zip(runnable, quotas, strict=False):
            if group is None or group_limit is None:
                filtered.append(function)
                continue
            if group_active_counts.get(group, 0) < group_limit:
                filtered.append(function)
            else:
                group_blocked.append(function)

        if group_blocked:
            await asyncio.gather(
                *(
                    self.record_dispatch_reason(fn, DispatchReason.NO_CAPACITY)
                    for fn in group_blocked
                )
            )
        return filtered

    def _fair_order_functions(self, functions: list[str]) -> list[str]:
        if not functions:
            return []
        count = len(functions)
        start = self._fair_dequeue_cursor % count
        ordered = functions[start:] + functions[:start]
        self._fair_dequeue_cursor = (start + 1) % count
        return ordered

    async def _xadd_job_payload(
        self,
        stream_key: str,
        *,
        job_id: str,
        function: str,
        data: str,
    ) -> None:
        client = await self._ensure_connected()
        payload = {"job_id": job_id, "function": function, "data": data}
        if self._stream_maxlen > 0:
            await client.xadd(
                stream_key,
                payload,
                maxlen=self._stream_maxlen,
                approximate=True,
            )
        else:
            await client.xadd(stream_key, payload)

    @staticmethod
    def _decode_text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    def _dlq_payload(self, job: Job, reason: str | None) -> dict[str, Any]:
        failed_at = (job.completed_at or datetime.now(UTC)).isoformat()
        return {
            "job_id": job.id,
            "function": job.function,
            "failed_at": failed_at,
            "reason": reason or "",
            "attempts": job.attempts,
            "max_retries": job.max_retries,
            "data": job.to_json(),
        }

    async def _write_dead_letter(
        self,
        client: Any,
        job: Job,
        reason: str | None,
    ) -> None:
        stream_key = self._dlq_stream_key(job.function)
        payload = self._dlq_payload(job, reason)
        if self._dlq_stream_maxlen > 0:
            await client.xadd(stream_key, payload, maxlen=self._dlq_stream_maxlen)
        else:
            await client.xadd(stream_key, payload)

    async def _delete_stream_entries_for_job(
        self,
        stream_key: str,
        job_id: str,
        *,
        batch_size: int = 500,
        max_scan: int = 50_000,
    ) -> int:
        """Delete stream entries matching a job_id (best effort, cancel path only)."""
        client = await self._ensure_connected()
        return await shared_delete_stream_entries_for_job(
            client,
            stream_key,
            job_id,
            batch_size=batch_size,
            max_scan=max_scan,
        )

    # =========================================================================
    # CORE - enqueue
    # =========================================================================

    async def enqueue(self, job: Job, *, delay: float = 0.0) -> str:
        """Add a job to the queue."""
        client = await self._ensure_connected()
        now = time.time()

        stream_key = self._stream_key(job.function)
        scheduled_key = self._scheduled_key(job.function)
        dedup_key = self._dedup_key(job.function)
        job_key = self._job_key(job)
        job_index_key = self._job_index_key(job.id)

        run_at = now + delay if delay > 0 else now
        job.scheduled_at = datetime.fromtimestamp(run_at, UTC)
        job.mark_queued()

        if delay <= 0:
            await self._ensure_consumer_group(stream_key)

        if self._enqueue_sha:
            dest_key = scheduled_key if delay > 0 else stream_key
            scheduled_time = run_at if delay > 0 else 0

            result = await self._evalsha_with_reload(
                "_enqueue_sha",
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
                str(self._stream_maxlen),
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
                await self._xadd_job_payload(
                    stream_key,
                    job_id=job.id,
                    function=job.function,
                    data=job.to_json(),
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

        runnable_functions = await self.get_runnable_functions(functions)
        runnable_functions = self._fair_order_functions(runnable_functions)
        if not runnable_functions:
            await asyncio.sleep(min(timeout, 0.25))
            return None

        deadline = time.time() + timeout
        stream_keys = {self._stream_key(fn): fn for fn in runnable_functions}

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
                    block=min(remaining_ms, 1000),
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

        runnable_functions = await self.get_runnable_functions(functions)
        runnable_functions = self._fair_order_functions(runnable_functions)
        if not runnable_functions:
            await asyncio.sleep(min(timeout, 0.25))
            return []

        deadline = time.time() + timeout
        stream_keys = {self._stream_key(fn): fn for fn in runnable_functions}

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
                    block=min(remaining_ms, 1000),
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

        # Resolve canonical active job payload; stream entries can be stale.
        job_key: str
        parsed_job_id: str | None = None
        job_data_raw = msg_data.get(b"data") or msg_data.get("data")
        if job_data_raw:
            job_str = (
                job_data_raw.decode()
                if isinstance(job_data_raw, bytes)
                else job_data_raw
            )
            try:
                stream_job = Job.from_json(job_str)
            except Exception:
                logger.warning(
                    "Skipping invalid stream payload stream=%s msg_id=%s",
                    stream_key,
                    msg_id_str,
                )
                await client.xack(stream_key, self._consumer_group, msg_id_str)
                return None
            job_key = self._job_key(stream_job)
            parsed_job_id = stream_job.id
        else:
            # Fallback for old messages
            job_id_raw = msg_data.get(b"job_id") or msg_data.get("job_id")
            if not job_id_raw:
                await client.xack(stream_key, self._consumer_group, msg_id_str)
                return None

            job_id = (
                job_id_raw.decode() if isinstance(job_id_raw, bytes) else job_id_raw
            )
            parsed_job_id = job_id
            function_raw = msg_data.get(b"function") or msg_data.get("function")
            function = (
                function_raw.decode()
                if isinstance(function_raw, bytes)
                else function_raw or "unknown"
            )

            job_key = self._key("job", function, job_id)

        job_data = await client.get(job_key)
        if not job_data:
            # ACK only if the job already reached terminal state and payload was
            # legitimately removed. Otherwise keep pending for investigation/replay.
            if parsed_job_id and await client.exists(self._result_key(parsed_job_id)):
                await client.xack(stream_key, self._consumer_group, msg_id_str)
            else:
                logger.warning(
                    "Missing active job payload for stream=%s msg_id=%s; leaving pending",
                    stream_key,
                    msg_id_str,
                )
            return None

        job_str = job_data.decode() if isinstance(job_data, bytes) else job_data
        try:
            job = Job.from_json(job_str)
        except Exception:
            logger.warning(
                "Skipping invalid canonical job payload key=%s stream=%s msg_id=%s",
                job_key,
                stream_key,
                msg_id_str,
            )
            await client.xack(stream_key, self._consumer_group, msg_id_str)
            return None

        rate_limit = await self._function_rate_limit(job.function)
        max_concurrency = await self._function_max_concurrency(job.function)
        if max_concurrency is not None:
            active_count = await self._function_active_count(job.function)
            if active_count > max_concurrency:
                await self.record_dispatch_reason(
                    job.function,
                    DispatchReason.NO_CAPACITY,
                    job_id=job.id,
                )
                self._set_stream_claim(job.id, stream_key=stream_key, msg_id=msg_id_str)
                await self.retry(job, delay=0.1)
                self._invalidate_function_active_count(job.function)
                return None

        group, group_limit = await self._function_group_quota(job.function)
        if group is not None and group_limit is not None:
            group_active = await self._group_active_count(group)
            if group_active > group_limit:
                await self.record_dispatch_reason(
                    job.function,
                    DispatchReason.NO_CAPACITY,
                    job_id=job.id,
                )
                self._set_stream_claim(job.id, stream_key=stream_key, msg_id=msg_id_str)
                await self.retry(job, delay=0.1)
                self._invalidate_function_active_count(job.function)
                return None

        if rate_limit is not None:
            allowed = await self._acquire_rate_limit_token(job.function, rate_limit)
            if not allowed:
                await self.record_dispatch_reason(
                    job.function,
                    DispatchReason.RATE_LIMITED,
                    job_id=job.id,
                )
                self._set_stream_claim(job.id, stream_key=stream_key, msg_id=msg_id_str)
                await self.retry(job, delay=rate_limit.token_interval_seconds)
                self._invalidate_function_active_count(job.function)
                return None

        # Store stream claim for later ACK/retry bookkeeping.
        self._set_stream_claim(job.id, stream_key=stream_key, msg_id=msg_id_str)

        job.status = JobStatus.ACTIVE
        job.started_at = datetime.now(UTC)
        await self._refresh_job_ttl(client, job, job_key=job_key)
        self._invalidate_function_active_count(job.function)

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

        claim = self._pop_stream_claim(job.id)
        msg_id = claim.msg_id if claim else None
        stream_key = claim.stream_key if claim else None
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
        pubsub_channel = job_status_channel(job.id)

        if self._finish_sha:
            await self._evalsha_with_reload(
                "_finish_sha",
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
                str(self._result_ttl_seconds),
                job.key or "",
                status.value,
            )
        else:
            if msg_id:
                await client.xack(stream_key, self._consumer_group, msg_id)
            await client.setex(
                result_key, self._result_ttl_seconds, job.to_json().encode()
            )
            await client.delete(job_key)
            await client.delete(job_index_key)
            if job.key:
                await client.srem(dedup_key, job.key)
            await client.publish(pubsub_channel, status.value)

        if status == JobStatus.FAILED:
            await self._write_dead_letter(client, job, error)

        # Job has terminally finished; clear cancellation marker if present.
        await client.delete(self._cancel_marker_key(job.id))
        self._invalidate_function_active_count(job.function)

    # =========================================================================
    # CORE - retry, cancel, get_job
    # =========================================================================

    async def retry(self, job: Job, delay: float) -> None:
        """Reschedule job for retry."""
        client = await self._ensure_connected()
        now = time.time()

        claim = self._pop_stream_claim(job.id)
        msg_id = claim.msg_id if claim else None
        old_stream_key = claim.stream_key if claim else None

        run_at = now + delay if delay > 0 else now
        job.scheduled_at = datetime.fromtimestamp(run_at, UTC)
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
            await self._evalsha_with_reload(
                "_retry_sha",
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
                str(self._stream_maxlen),
            )
        else:
            # Fallback without Lua
            if msg_id and old_stream_key:
                await client.xack(old_stream_key, self._consumer_group, msg_id)

            await client.setex(job_key, self._job_ttl_seconds, job.to_json().encode())
            await client.setex(job_index_key, self._job_ttl_seconds, job_key)

            if delay > 0:
                await client.zadd(dest_key, {job.id: run_at})
            else:
                await self._xadd_job_payload(
                    dest_key,
                    job_id=job.id,
                    function=job.function,
                    data=job.to_json(),
                )
        self._invalidate_function_active_count(job.function)

    async def manual_retry(self, job: Job) -> None:
        """Requeue a terminal job for operator-initiated retry."""
        if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ValueError(
                f"Job {job.id} cannot be retried from status '{job.status.value}'"
            )

        client = await self._ensure_connected()
        self._pop_stream_claim(job.id)

        prepare_job_for_manual_retry(job)

        stream_key = self._stream_key(job.function)
        scheduled_key = self._scheduled_key(job.function)
        dedup_key = self._dedup_key(job.function)
        job_key = self._job_key(job)
        job_index_key = self._job_index_key(job.id)

        if job.key and await client.sismember(dedup_key, job.key):
            raise DuplicateJobError(
                f"idempotency key '{job.key}' is already active for {job.function}"
            )

        await self._ensure_consumer_group(stream_key)

        payload_json = job.to_json()
        payload = {"job_id": job.id, "function": job.function, "data": payload_json}
        async with client.pipeline(transaction=True) as pipe:
            pipe.setex(job_key, self._job_ttl_seconds, payload_json)
            pipe.setex(job_index_key, self._job_ttl_seconds, job_key)
            pipe.delete(self._result_key(job.id))
            pipe.delete(self._cancel_marker_key(job.id))
            pipe.zrem(scheduled_key, job.id)
            if job.key:
                pipe.sadd(dedup_key, job.key)
                pipe.expire(dedup_key, self._job_ttl_seconds)
            if self._stream_maxlen > 0:
                pipe.xadd(stream_key, payload, maxlen=self._stream_maxlen)
            else:
                pipe.xadd(stream_key, payload)
            await pipe.execute()

        self._invalidate_function_active_count(job.function)

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

        # Update job status for result storage.
        job.mark_cancelled()

        claim = self._pop_stream_claim(job.id)
        msg_id = claim.msg_id if claim else None
        stream_key = self._stream_key(job.function)
        scheduled_key = self._scheduled_key(job.function)
        result_key = self._result_key(job.id)
        job_index_key = self._job_index_key(job.id)
        dedup_key = self._dedup_key(job.function)
        cancel_marker_key = self._cancel_marker_key(job.id)
        pubsub_channel = job_status_channel(job.id)

        # Mark cancellation immediately so workers can skip already-prefetched jobs.
        # Use NX so concurrent cancels do not clobber each other's marker lifetime.
        marker_created = bool(
            await client.set(
                cancel_marker_key,
                b"1",
                ex=self._job_ttl_seconds,
                nx=True,
            )
        )

        # Use Lua script for atomic cancellation if available
        cancelled = False
        if self._cancel_sha:
            result = await self._evalsha_with_reload(
                "_cancel_sha",
                6,  # number of keys
                stream_key,
                result_key,
                job_key,
                job_index_key,
                dedup_key,
                pubsub_channel,
                self._consumer_group,
                msg_id or "",
                job.to_json(),
                str(self._result_ttl_seconds),
                job.key or "",
            )
            result_text = result.decode() if isinstance(result, bytes) else str(result)
            cancelled = result_text == "OK"
        else:
            # Fallback without Lua
            stored = await client.set(
                result_key,
                job.to_json().encode(),
                ex=self._result_ttl_seconds,
                nx=True,
            )
            cancelled = bool(stored)
            if not cancelled:
                if marker_created:
                    await client.delete(cancel_marker_key)
                return False
            if msg_id:
                await client.xack(stream_key, self._consumer_group, msg_id)
            await client.delete(job_key)
            await client.delete(job_index_key)
            if job.key:
                await client.srem(dedup_key, job.key)
            await client.publish(pubsub_channel, JobStatus.CANCELLED.value)

        if not cancelled:
            if marker_created:
                await client.delete(cancel_marker_key)
            return False

        # Remove queued copies from scheduled and stream storage (best effort).
        await client.zrem(scheduled_key, job.id)
        deleted_from_stream = await self._delete_stream_entries_for_job(
            stream_key, job.id
        )
        if deleted_from_stream > 0:
            logger.debug(
                "Deleted %s queued stream entries for cancelled job %s",
                deleted_from_stream,
                job.id,
            )

        self._invalidate_function_active_count(job.function)
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
    # OPTIONAL - progress, heartbeat, checkpoint
    # =========================================================================

    async def update_progress(self, job_id: str, progress: float) -> None:
        client = await self._ensure_connected()
        job_key = await self._find_job_key_by_id(job_id)
        if job_key is None:
            return

        job_data = await client.get(job_key)
        if not job_data:
            return

        job = Job.from_json(
            job_data.decode() if isinstance(job_data, bytes) else job_data
        )
        if job.progress == progress:
            return

        job.progress = progress
        await client.setex(job_key, self._job_ttl_seconds, job.to_json())

    async def is_cancelled(self, job_id: str) -> bool:
        client = await self._ensure_connected()
        marker = await client.get(self._cancel_marker_key(job_id))
        return marker is not None

    async def heartbeat_active_jobs(self, jobs: list[Job]) -> None:
        """Reset idle time on active jobs to prevent XAUTOCLAIM from reclaiming them."""
        if not jobs:
            return

        client = await self._ensure_connected()

        # Group by stream key for efficient pipelining
        by_stream: dict[str, list[str]] = {}
        for job in jobs:
            claim = self._peek_stream_claim(job.id)
            if claim is None:
                continue
            by_stream.setdefault(claim.stream_key, []).append(claim.msg_id)

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
        await self._refresh_job_ttls(client, jobs)

    async def _refresh_job_ttl(
        self,
        client: Any,
        job: Job,
        *,
        job_key: str | None = None,
    ) -> None:
        if self._job_ttl_seconds <= 0:
            return
        key = job_key or self._job_key(job)
        index_key = self._job_index_key(job.id)
        try:
            async with client.pipeline(transaction=False) as pipe:
                pipe.expire(key, self._job_ttl_seconds)
                pipe.expire(index_key, self._job_ttl_seconds)
                await pipe.execute()
        except Exception:
            logger.debug("Failed refreshing TTL for job %s", job.id)

    async def _refresh_job_ttls(self, client: Any, jobs: list[Job]) -> None:
        if not jobs or self._job_ttl_seconds <= 0:
            return
        try:
            async with client.pipeline(transaction=False) as pipe:
                for job in jobs:
                    pipe.expire(self._job_key(job), self._job_ttl_seconds)
                    pipe.expire(self._job_index_key(job.id), self._job_ttl_seconds)
                await pipe.execute()
        except Exception:
            logger.debug("Failed refreshing TTL for %s active jobs", len(jobs))

    async def update_job_checkpoint(
        self,
        job_id: str,
        state: dict[str, Any],
        checkpointed_at: str,
    ) -> None:
        client = await self._ensure_connected()
        if not state:
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
        job.checkpoint = state
        job.checkpoint_at = checkpointed_at

        await client.setex(job_key, self._job_ttl_seconds, job.to_json())

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
        match = job_match_pattern(job_id, key_prefix=self._key_prefix)
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
        terminal_status = await self._terminal_job_status(job_id)
        if terminal_status is not None:
            return terminal_status

        pubsub = client.pubsub()
        channel = job_status_channel(job_id)
        await pubsub.subscribe(channel)

        try:
            # Close the race between initial status check and subscribe setup.
            terminal_status = await self._terminal_job_status(job_id)
            if terminal_status is not None:
                return terminal_status

            deadline = None if timeout is None else time.time() + timeout

            while True:
                now = time.time()
                if deadline is not None:
                    remaining = deadline - now
                    if remaining <= 0:
                        terminal_status = await self._terminal_job_status(job_id)
                        if terminal_status is not None:
                            return terminal_status
                        break
                    poll_timeout = min(1.0, remaining)
                else:
                    poll_timeout = 1.0

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=poll_timeout,
                )

                if message and message["type"] == "message":
                    status = message["data"]
                    if isinstance(status, bytes):
                        return status.decode()
                    return str(status)

                terminal_status = await self._terminal_job_status(job_id)
                if terminal_status is not None:
                    return terminal_status

            raise TimeoutError(f"Timeout waiting for job {job_id}")

        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def _terminal_job_status(self, job_id: str) -> str | None:
        """Return terminal status for a job id when available."""
        job = await self.get_job(job_id)
        if job and job.status.is_terminal():
            return job.status.value
        return None

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
                cursor=cursor,
                match=function_stream_pattern(key_prefix=self._key_prefix),
                count=100,
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
                cursor=cursor,
                match=function_scheduled_pattern(key_prefix=self._key_prefix),
                count=100,
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

    async def get_dead_letters(
        self,
        function: str,
        *,
        limit: int = 100,
    ) -> list[DeadLetterEntry]:
        client = await self._ensure_connected()
        dlq_stream = self._dlq_stream_key(function)

        try:
            rows = await client.xrevrange(dlq_stream, count=max(1, limit))
        except redis.ResponseError:
            return []

        entries: list[DeadLetterEntry] = []
        for msg_id, msg_data in rows:
            data_raw = msg_data.get(b"data") or msg_data.get("data")
            if not data_raw:
                continue

            try:
                job = Job.from_json(self._decode_text(data_raw))
            except Exception:
                continue

            failed_at_raw = msg_data.get(b"failed_at") or msg_data.get("failed_at")
            failed_at = None
            if failed_at_raw:
                try:
                    failed_at = datetime.fromisoformat(self._decode_text(failed_at_raw))
                except ValueError:
                    failed_at = None

            reason_raw = msg_data.get(b"reason") or msg_data.get("reason")
            reason = self._decode_text(reason_raw) if reason_raw else None
            if reason == "":
                reason = None

            entries.append(
                DeadLetterEntry(
                    entry_id=self._decode_text(msg_id),
                    function=function,
                    job=job,
                    failed_at=failed_at,
                    reason=reason,
                )
            )

        return entries

    async def replay_dead_letter(self, function: str, entry_id: str) -> str | None:
        client = await self._ensure_connected()
        dlq_stream = self._dlq_stream_key(function)
        rows = await client.xrange(dlq_stream, min=entry_id, max=entry_id, count=1)
        if not rows:
            return None

        _msg_id, msg_data = rows[0]
        data_raw = msg_data.get(b"data") or msg_data.get("data")
        if not data_raw:
            return None

        dead_job = Job.from_json(self._decode_text(data_raw))
        if dead_job.function != function:
            raise ValueError(
                f"Dead-letter function mismatch: expected '{function}', got '{dead_job.function}'"
            )

        replayed = Job(
            function=dead_job.function,
            function_name=dead_job.function_name,
            kwargs=dict(dead_job.kwargs),
            key=dead_job.key,
            timeout=dead_job.timeout,
            max_retries=dead_job.max_retries,
            retry_delay=dead_job.retry_delay,
            retry_backoff=dead_job.retry_backoff,
            parent_id=dead_job.parent_id,
            root_id=dead_job.root_id if dead_job.parent_id else "",
            source=clone_job_source(dead_job.source),
            checkpoint=dead_job.checkpoint,
            checkpoint_at=dead_job.checkpoint_at,
        )
        replayed.dlq_replayed_from = entry_id
        failed_at_raw = msg_data.get(b"failed_at") or msg_data.get("failed_at")
        if failed_at_raw:
            replayed.dlq_failed_at = self._decode_text(failed_at_raw)

        new_job_id = await self.enqueue(replayed)
        await client.xdel(dlq_stream, entry_id)
        return new_job_id

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

    def _cron_cursor_key(self) -> str:
        return self._key("cron_cursor")

    async def _write_cron_cursor(
        self,
        client: Any,
        *,
        function: str,
        next_run_at: float,
        last_completed_at: datetime | None = None,
    ) -> None:
        payload = _CronCursorRecord(
            function=function,
            next_run_at=datetime.fromtimestamp(next_run_at, UTC),
            last_completed_at=last_completed_at,
            updated_at=datetime.now(UTC),
        )
        await client.hset(self._cron_cursor_key(), function, payload.model_dump_json())

    async def _read_cron_cursor(
        self,
        client: Any,
        *,
        function: str,
    ) -> _CronCursorRecord | None:
        raw = await client.hget(self._cron_cursor_key(), function)
        if not raw:
            return None
        try:
            return _CronCursorRecord.model_validate_json(self._decode_text(raw))
        except Exception:
            return None

    async def _cron_reconcile_policy(
        self,
        function: str,
    ) -> tuple[MissedRunPolicy, float | None]:
        config = await self._read_function_config(function)
        if config is None:
            return (MissedRunPolicy.CATCH_UP, None)
        max_window = config.max_catch_up_seconds
        if max_window is not None and max_window <= 0:
            logger.warning(
                "Invalid max_catch_up_seconds for function '%s': %s",
                function,
                max_window,
            )
            max_window = None
        return (
            config.missed_run_policy or MissedRunPolicy.CATCH_UP,
            max_window,
        )

    def _cron_missed_windows(
        self,
        *,
        schedule: str,
        next_run_at: float,
        now_ts: float,
        max_catch_up_seconds: float | None,
    ) -> list[float]:
        if next_run_at > now_ts:
            return []

        cutoff = (
            now_ts - max_catch_up_seconds if max_catch_up_seconds is not None else None
        )
        windows: list[float] = []
        cursor_ts = next_run_at

        # Hard guard against pathological schedules with huge backlog.
        for _ in range(10_000):
            if cursor_ts > now_ts:
                break
            if cutoff is None or cursor_ts >= cutoff:
                windows.append(cursor_ts)

            next_dt = calculate_next_cron_run(
                schedule,
                datetime.fromtimestamp(cursor_ts, UTC),
            )
            next_ts = next_dt.timestamp()
            if next_ts <= cursor_ts:
                break
            cursor_ts = next_ts

        return windows

    async def seed_cron(self, job: Job, next_run_at: float) -> bool:
        client = await self._ensure_connected()

        cron_registry = self._cron_registry_key()
        cron_key = f"cron:{job.function}"

        was_set = await client.hsetnx(cron_registry, cron_key, job.id)
        if not was_set:
            return False

        reserved, owner = await self._reserve_cron_window(
            client,
            function=job.function,
            run_at=next_run_at,
            job_id=job.id,
        )
        if not reserved:
            if owner:
                await client.hset(cron_registry, cron_key, owner)
            return False

        job.key = f"cron:{job.function}:{self._cron_window_token(next_run_at)}"
        job.scheduled_at = datetime.fromtimestamp(next_run_at, UTC)
        job.mark_queued("Cron job scheduled")
        job.cron_window_at = next_run_at
        job_key = self._job_key(job)
        await client.setex(job_key, self._job_ttl_seconds, job.to_json().encode())

        scheduled_key = self._scheduled_key(job.function)
        await client.zadd(scheduled_key, {job.id: next_run_at})

        await self._write_cron_cursor(
            client,
            function=job.function,
            next_run_at=next_run_at,
            last_completed_at=None,
        )
        await self._update_function_next_run(client, job.function, next_run_at)

        return True

    async def reschedule_cron(self, job: Job, next_run_at: float) -> str:
        client = await self._ensure_connected()
        cron_registry = self._cron_registry_key()
        cron_key = f"cron:{job.function}"
        schedule = job.schedule
        if not schedule:
            raise ValueError(f"Cron job '{job.id}' is missing schedule")

        new_job = Job(
            function=job.function,
            function_name=job.function_name,
            kwargs=job.kwargs,
            key=f"cron:{job.function}:{self._cron_window_token(next_run_at)}",
            timeout=job.timeout,
            source=CronSource(
                schedule=schedule,
                cron_window_at=next_run_at,
                startup_reconciled=job.startup_reconciled,
                startup_policy=job.startup_policy,
            ),
            checkpoint=job.checkpoint,
            checkpoint_at=job.checkpoint_at,
        )
        new_job.scheduled_at = datetime.fromtimestamp(next_run_at, UTC)
        new_job.mark_queued("Cron job rescheduled")

        reserved, owner = await self._reserve_cron_window(
            client,
            function=job.function,
            run_at=next_run_at,
            job_id=new_job.id,
        )
        if not reserved:
            if owner:
                await client.hset(cron_registry, cron_key, owner)
                return owner
            current_job_id = await client.hget(cron_registry, cron_key)
            if current_job_id:
                return self._decode_text(current_job_id)
            return new_job.id

        await client.hset(cron_registry, cron_key, new_job.id)

        job_key = self._job_key(new_job)
        await client.setex(job_key, self._job_ttl_seconds, new_job.to_json().encode())

        scheduled_key = self._scheduled_key(new_job.function)
        await client.zadd(scheduled_key, {new_job.id: next_run_at})

        await self._write_cron_cursor(
            client,
            function=job.function,
            next_run_at=next_run_at,
            last_completed_at=job.completed_at,
        )
        await self._update_function_next_run(client, job.function, next_run_at)

        return new_job.id

    async def reconcile_cron_startup(
        self,
        job: Job,
        *,
        now_ts: float | None = None,
    ) -> bool:
        client = await self._ensure_connected()
        current_ts = time.time() if now_ts is None else now_ts

        cursor = await self._read_cron_cursor(client, function=job.function)
        if not cursor:
            return False

        next_run_at = cursor.next_run_at.timestamp()

        if next_run_at > current_ts:
            return False

        cron_registry = self._cron_registry_key()
        cron_key = f"cron:{job.function}"
        current_job_id = await client.hget(cron_registry, cron_key)
        if isinstance(current_job_id, bytes):
            current_job_id = current_job_id.decode()

        if current_job_id:
            scheduled_key = self._scheduled_key(job.function)
            scheduled_score = await client.zscore(scheduled_key, current_job_id)
            job_key = self._key("job", job.function, current_job_id)
            if scheduled_score is not None or await client.exists(job_key):
                # A cron run is already present; no extra catch-up enqueue needed.
                return False

        schedule = job.schedule
        if not schedule:
            logger.warning(
                "Skipping cron startup reconciliation for %s: missing schedule",
                job.function,
            )
            return False
        policy, max_window = await self._cron_reconcile_policy(job.function)
        missed_windows = self._cron_missed_windows(
            schedule=schedule,
            next_run_at=next_run_at,
            now_ts=current_ts,
            max_catch_up_seconds=max_window,
        )

        if policy == MissedRunPolicy.SKIP or not missed_windows:
            base_ts = missed_windows[-1] if missed_windows else current_ts
            next_future = calculate_next_cron_run(
                schedule,
                datetime.fromtimestamp(base_ts, UTC),
            )
            await self._write_cron_cursor(
                client,
                function=job.function,
                next_run_at=next_future.timestamp(),
                last_completed_at=cursor.last_completed_at,
            )
            await self._update_function_next_run(
                client,
                job.function,
                next_future.timestamp(),
            )
            return False

        selected_window = (
            missed_windows[-1]
            if policy == MissedRunPolicy.LATEST_ONLY
            else missed_windows[0]
        )

        catchup_job = Job(
            function=job.function,
            function_name=job.function_name,
            kwargs=job.kwargs,
            key=f"cron:{job.function}:{self._cron_window_token(selected_window)}",
            timeout=job.timeout,
            source=CronSource(
                schedule=schedule,
                cron_window_at=selected_window,
                startup_reconciled=True,
                startup_policy=(
                    MissedRunPolicy.LATEST_ONLY
                    if policy == MissedRunPolicy.LATEST_ONLY
                    else MissedRunPolicy.CATCH_UP
                ).value,
            ),
            checkpoint=job.checkpoint,
            checkpoint_at=job.checkpoint_at,
        )
        catchup_job.scheduled_at = datetime.fromtimestamp(selected_window, UTC)
        if policy == MissedRunPolicy.LATEST_ONLY:
            catchup_job.mark_queued("Cron startup reconciliation latest-only run")
        else:
            catchup_job.mark_queued("Cron startup reconciliation catch-up")

        reserved, owner = await self._reserve_cron_window(
            client,
            function=job.function,
            run_at=selected_window,
            job_id=catchup_job.id,
        )
        if not reserved:
            if owner:
                await client.hset(cron_registry, cron_key, owner)
            return False

        try:
            await self.enqueue(catchup_job, delay=0)
        except DuplicateJobError:
            return False

        await client.hset(cron_registry, cron_key, catchup_job.id)

        next_future = calculate_next_cron_run(
            schedule,
            datetime.fromtimestamp(selected_window, UTC),
        )

        await self._write_cron_cursor(
            client,
            function=job.function,
            next_run_at=next_future.timestamp(),
            last_completed_at=cursor.last_completed_at,
        )
        await self._update_function_next_run(
            client,
            job.function,
            next_future.timestamp(),
        )
        return True

    async def _update_function_next_run(
        self, client: redis.Redis, function_name: str, next_run_at: float
    ) -> None:
        """Update the function definition in Redis with the next scheduled run time."""
        func_key = function_definition_key(function_name)
        data = await client.get(func_key)
        config = self._parse_function_config(data, key_hint=func_key)
        if config is None:
            return
        updated = config.model_copy(
            update={"next_run_at": datetime.fromtimestamp(next_run_at, UTC).isoformat()}
        )
        serialized = updated.model_dump_json()
        self._function_config_cache[function_name] = (updated, time.time() + 1.0)
        ttl = await client.ttl(func_key)
        if ttl > 0:
            await client.setex(func_key, ttl, serialized)
        else:
            await client.set(func_key, serialized)
