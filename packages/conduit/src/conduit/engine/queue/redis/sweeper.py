"""Background sweeper for RedisQueue.

Moves scheduled jobs to streams when they become due.
"""

import asyncio
import logging
import time
from uuid import uuid4
from typing import TYPE_CHECKING

from conduit.engine.queue.redis.constants import DEFAULT_STREAM_MAXLEN

if TYPE_CHECKING:
    from conduit.engine.queue.redis.queue import RedisQueue

logger = logging.getLogger(__name__)

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
        self._sweep_interval = sweep_interval
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background sweep loop."""
        if self._task is not None:
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._sweep_loop())
        logger.debug(f"Sweeper started (interval={self._sweep_interval})")

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
            try:
                # Try to acquire lock (expires after 60s to prevent deadlock)
                lock_token = uuid4().hex
                acquired = await client.set(
                    lock_key,
                    lock_token,
                    nx=True,
                    ex=60,
                )

                if acquired:
                    try:
                        await self._do_sweep()
                    finally:
                        await client.eval(RELEASE_LOCK_SCRIPT, 1, lock_key, lock_token)

            except Exception as e:
                logger.debug(f"Sweep error: {e}")

            await asyncio.sleep(self._sweep_interval)

    async def _do_sweep(self) -> None:
        """Move due scheduled jobs to their streams."""
        client = await self._queue._ensure_connected()
        now = time.time()

        # Scan all scheduled ZSETs
        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor=cursor,
                match=f"{self._queue._key_prefix}:fn:*:scheduled",
                count=100,
            )

            for scheduled_key in keys:
                key_str = (
                    scheduled_key.decode()
                    if isinstance(scheduled_key, bytes)
                    else scheduled_key
                )

                # Extract function name from key
                parts = key_str.split(":")
                fn_idx = parts.index("fn") + 1
                function = parts[fn_idx]

                stream_key = self._queue._stream_key(function)
                await self._queue._ensure_consumer_group(stream_key)

                # Use Lua script for atomic sweep if available
                if self._queue._sweep_sha:
                    moved = await client.evalsha(
                        self._queue._sweep_sha,
                        2,
                        key_str,
                        stream_key,
                        str(now),
                        function,
                        "100",
                        str(DEFAULT_STREAM_MAXLEN),
                        self._queue._key_prefix,
                    )
                    if moved and moved > 0:
                        logger.debug(f"Swept {moved} scheduled jobs for {function}")
                else:
                    await self._sweep_fallback(
                        client, key_str, stream_key, function, now
                    )

            if cursor == 0:
                break

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
            job_key = self._queue._key("job", function, job_id_str)
            job_data = await client.get(job_key)

            msg_fields: dict[str, str] = {
                "job_id": job_id_str,
                "function": function,
            }
            if job_data:
                job_data_str = (
                    job_data.decode() if isinstance(job_data, bytes) else job_data
                )
                msg_fields["data"] = job_data_str

            await client.xadd(
                stream_key,
                msg_fields,
                maxlen=DEFAULT_STREAM_MAXLEN,
                approximate=True,
            )

            await client.zrem(scheduled_key, job_id_str)
            logger.debug(f"Moved scheduled job {job_id_str} to stream")
