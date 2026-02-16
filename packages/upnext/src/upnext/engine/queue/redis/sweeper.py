"""Background sweeper for RedisQueue.

Moves scheduled jobs to streams when they become due.
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from shared.keys import function_scheduled_key, job_key

if TYPE_CHECKING:
    from upnext.engine.queue.redis.queue import RedisQueue

logger = logging.getLogger(__name__)

SWEEPER_MIN_SLEEP_SECONDS = 0.1  # 100ms
SWEEPER_MAX_SLEEP_SECONDS = 3.0  # 3s
SWEEPER_LOCK_TTL_SECONDS = 60

RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""


class Sweeper:
    """Background task that moves scheduled jobs to streams when due."""

    def __init__(
        self,
        queue: "RedisQueue",
        *,
        sweep_interval: float,
    ) -> None:
        self._queue = queue
        _ = sweep_interval
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._min_sleep_seconds = SWEEPER_MIN_SLEEP_SECONDS
        self._max_sleep_seconds = SWEEPER_MAX_SLEEP_SECONDS
        self._sweep_count: int = 0
        self._consumer_group_cleanup_interval: int = 100

    async def start(self) -> None:
        """Start the background sweep loop."""
        if self._task is not None:
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._sweep_loop())
        logger.debug(
            "Sweeper started (min_sleep=%.3fs, max_sleep=%.3fs)",
            self._min_sleep_seconds,
            self._max_sleep_seconds,
        )

    async def stop(self) -> None:
        """Stop the background sweep loop."""
        if self._task is None:
            return

        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.debug("Sweeper stopped")

    async def _sweep_loop(self) -> None:
        """Background loop that moves scheduled jobs to streams.

        Uses distributed lock so only one worker sweeps at a time.
        """
        client = await self._queue._ensure_connected()
        lock_key = self._queue._key("sweep_lock")

        while not self._stop_event.is_set():
            sleep_seconds = self._max_sleep_seconds
            try:
                # Try to acquire lock (expires after 60s to prevent deadlock)
                lock_token = uuid4().hex
                acquired = await client.set(
                    lock_key,
                    lock_token,
                    nx=True,
                    ex=SWEEPER_LOCK_TTL_SECONDS,
                )

                if acquired:
                    try:
                        await self._do_sweep()
                        next_due = await self._get_next_due_timestamp(client)
                        sleep_seconds = self._compute_sleep_seconds(next_due)
                    finally:
                        await client.eval(RELEASE_LOCK_SCRIPT, 1, lock_key, lock_token)
                else:
                    # Another worker currently leads sweeping; retry soon.
                    sleep_seconds = self._min_sleep_seconds

            except Exception as e:
                logger.debug(f"Sweep error: {e}")
                sleep_seconds = self._min_sleep_seconds

            await asyncio.sleep(sleep_seconds)

    def _compute_sleep_seconds(self, next_due_timestamp: float | None) -> float:
        """Clamp sweeper sleep time to bounded adaptive window."""
        if next_due_timestamp is None:
            return self._max_sleep_seconds

        delay = next_due_timestamp - time.time()
        return max(self._min_sleep_seconds, min(self._max_sleep_seconds, delay))

    async def _get_next_due_timestamp(self, client) -> float | None:
        """Return earliest scheduled score across all functions, if any."""
        earliest: float | None = None
        now = time.time()

        scheduled_keys = [
            function_scheduled_key(fn, key_prefix=self._queue._key_prefix)
            for fn in self._queue._registered_functions
        ]

        for scheduled_key in scheduled_keys:
            try:
                entries = await client.zrange(scheduled_key, 0, 0, withscores=True)
            except Exception:
                continue
            if not entries:
                continue

            _, raw_score = entries[0]
            score = float(raw_score)
            if earliest is None or score < earliest:
                earliest = score
                if earliest <= now:
                    return earliest

        return earliest

    async def _do_sweep(self) -> None:
        """Move due scheduled jobs to their streams."""
        self._sweep_count += 1
        if self._sweep_count % self._consumer_group_cleanup_interval == 0:
            try:
                await self._queue.cleanup_stale_consumer_groups()
            except Exception as e:
                logger.debug("Consumer group cleanup error: %s", e)

        client = await self._queue._ensure_connected()
        now = time.time()

        for function in self._queue._registered_functions:
            scheduled = function_scheduled_key(
                function, key_prefix=self._queue._key_prefix
            )
            stream_key = self._queue._stream_key(function)
            await self._queue._ensure_consumer_group(stream_key)

            if self._queue._sweep_sha:
                moved = await client.evalsha(
                    self._queue._sweep_sha,
                    2,
                    scheduled,
                    stream_key,
                    str(now),
                    function,
                    "100",
                    str(self._queue._stream_maxlen),
                    self._queue._key_prefix,
                )
                if moved and moved > 0:
                    logger.debug(f"Swept {moved} scheduled jobs for {function}")
            else:
                await self._sweep_fallback(client, scheduled, stream_key, function, now)

    async def _sweep_fallback(
        self,
        client,
        scheduled_key: str,
        stream_key: str,
        function: str,
        now: float,
    ) -> None:
        """Fallback sweep without Lua scripts."""
        due_jobs = await client.zrangebyscore(
            scheduled_key,
            "-inf",
            now,
            start=0,
            num=100,
        )

        if not due_jobs:
            return

        for job_id in due_jobs:
            job_id_str = job_id.decode() if isinstance(job_id, bytes) else job_id

            # Get job data for inline storage
            payload_key = job_key(
                function,
                job_id_str,
                key_prefix=self._queue._key_prefix,
            )
            job_data = await client.get(payload_key)

            msg_fields: dict[str, str] = {
                "job_id": job_id_str,
                "function": function,
            }
            if job_data:
                job_data_str = (
                    job_data.decode() if isinstance(job_data, bytes) else job_data
                )
                msg_fields["data"] = job_data_str

            if self._queue._stream_maxlen > 0:
                await client.xadd(
                    stream_key,
                    msg_fields,
                    maxlen=self._queue._stream_maxlen,
                    approximate=True,
                )
            else:
                await client.xadd(stream_key, msg_fields)

            await client.zrem(scheduled_key, job_id_str)
            logger.debug(f"Moved scheduled job {job_id_str} to stream")
