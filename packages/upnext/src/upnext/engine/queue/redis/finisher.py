"""Background job finisher for RedisQueue.

Batch-flushes completed jobs to Redis using pipelines.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from upnext.engine.queue.redis.constants import CompletedJob

if TYPE_CHECKING:
    from upnext.engine.queue.redis.queue import RedisQueue

logger = logging.getLogger(__name__)


class Finisher:
    """Background task that batch-flushes completed jobs to Redis."""

    def __init__(
        self,
        queue: "RedisQueue",
        *,
        batch_size: int,
        outbox_size: int,
        flush_interval: float,
    ) -> None:
        self._queue = queue
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._outbox: asyncio.Queue[CompletedJob] = asyncio.Queue(maxsize=outbox_size)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def outbox(self) -> asyncio.Queue[CompletedJob]:
        """The outbox queue for completed jobs waiting to be flushed."""
        return self._outbox

    async def start(self) -> None:
        """Start the background finish loop."""
        if self._task is not None:
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._finish_loop())
        logger.debug(f"Finisher started (flush_interval={self._flush_interval})")

    async def stop(self) -> None:
        """Stop the background finish loop, flushing remaining items."""
        if self._task is None:
            return

        self._stop_event.set()

        # Give the loop a chance to flush remaining items
        if not self._outbox.empty():
            logger.debug(f"Flushing {self._outbox.qsize()} remaining completions")
            await asyncio.sleep(0.1)

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.debug("Finisher stopped")

    async def put(self, completed: CompletedJob) -> None:
        """Add a completed job to the outbox for batch flushing."""
        await self._outbox.put(completed)

    async def _finish_loop(self) -> None:
        """Background loop that collects and batch-flushes completions."""
        batch: list[CompletedJob] = []

        while not self._stop_event.is_set() or not self._outbox.empty():
            # Collect jobs up to batch_size or flush_interval
            try:
                async with asyncio.timeout(self._flush_interval):
                    while len(batch) < self._batch_size:
                        batch.append(await self._outbox.get())
            except (TimeoutError, asyncio.CancelledError):
                pass

            # Flush batch
            if batch:
                try:
                    await self._flush_batch(batch)
                except Exception as e:
                    logger.error(f"Finish loop flush error: {e}", exc_info=True)
                batch = []

    async def _flush_batch(self, batch: list[CompletedJob]) -> None:
        """Flush completed jobs using Redis pipeline."""
        client = await self._queue._ensure_connected()

        async with client.pipeline(transaction=False) as pipe:
            for completed in batch:
                job = completed.job
                msg_id = job.metadata.get("_stream_msg_id") if job.metadata else None
                stream_key = job.metadata.get("_stream_key") if job.metadata else None
                if not stream_key:
                    stream_key = self._queue._stream_key(job.function)

                job.status = completed.status
                job.completed_at = datetime.now(UTC)
                job.result = completed.result
                job.error = completed.error

                if self._queue._finish_sha:
                    pipe.evalsha(
                        self._queue._finish_sha,
                        6,
                        stream_key,
                        self._queue._result_key(job.id),
                        self._queue._job_key(job),
                        self._queue._job_index_key(job.id),
                        self._queue._dedup_key(job.function),
                        f"upnext:job:{job.id}",
                        self._queue._consumer_group,
                        msg_id or "",
                        job.to_json(),
                        "3600",
                        job.key or "",
                        completed.status.value,
                    )
                else:
                    # Fallback without Lua scripts
                    if msg_id:
                        pipe.xack(stream_key, self._queue._consumer_group, msg_id)
                    pipe.setex(
                        self._queue._result_key(job.id), 3600, job.to_json().encode()
                    )
                    pipe.delete(self._queue._job_key(job))
                    pipe.delete(self._queue._job_index_key(job.id))
                    if job.key:
                        pipe.srem(self._queue._dedup_key(job.function), job.key)
                    pipe.publish(f"upnext:job:{job.id}", completed.status.value)

            await pipe.execute()

        logger.debug(f"Flushed {len(batch)} completed jobs")
