"""Background job fetcher for RedisQueue.

Batch-fetches jobs from Redis and populates an internal inbox queue.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from shared import Job

if TYPE_CHECKING:
    from upnext.engine.queue.redis.queue import RedisQueue

logger = logging.getLogger(__name__)


class Fetcher:
    """Background task that batch-fetches jobs into an inbox queue."""

    def __init__(
        self,
        queue: "RedisQueue",
        *,
        batch_size: int,
        inbox_size: int,
    ) -> None:
        self._queue = queue
        self._batch_size = batch_size
        self._inbox: asyncio.Queue[Job] = asyncio.Queue(maxsize=inbox_size)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._functions: list[str] = []

    @property
    def inbox(self) -> asyncio.Queue[Job]:
        """The inbox queue containing fetched jobs."""
        return self._inbox

    async def start(
        self,
        functions: list[str],
    ) -> None:
        """Start the background fetch loop."""
        if self._task is not None:
            return

        self._functions = functions
        self._stop_event.clear()
        self._task = asyncio.create_task(self._fetch_loop())
        logger.debug(
            f"Fetcher started (batch_size={self._batch_size}, functions={functions})"
        )

    async def stop(self) -> None:
        """Stop the background fetch loop."""
        if self._task is None:
            return

        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.debug("Fetcher stopped")

    async def _fetch_loop(self) -> None:
        """Background loop that batch-fetches jobs and populates inbox."""
        logger.debug(f"Fetch loop started, functions={self._functions}")

        while not self._stop_event.is_set():
            # Refill whenever capacity is available; waiting for a full batch can
            # starve consumers when only partial capacity is free.
            available = self._inbox.maxsize - self._inbox.qsize()
            if available <= 0:
                await asyncio.sleep(0.005)
                continue

            try:
                target_count = min(self._batch_size, available)
                block_timeout = 1.0 if target_count >= self._batch_size else 0.05
                jobs = await self._queue._dequeue_batch(
                    self._functions,
                    count=target_count,
                    timeout=block_timeout,
                )
                if not jobs:
                    await asyncio.sleep(0.005)
                    continue
                for job in jobs:
                    await self._inbox.put(job)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Fetch loop error: {e}", exc_info=True)
                await asyncio.sleep(0.1)
