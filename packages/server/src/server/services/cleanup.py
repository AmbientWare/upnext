"""Periodic cleanup service for old job history and artifacts.

Runs on a configurable interval, using a Redis distributed lock
so only one server instance performs cleanup at a time.
"""

import asyncio
import logging
from typing import Any

from server.db.repository import JobRepository
from server.db.session import get_database

logger = logging.getLogger(__name__)

CLEANUP_LOCK_KEY = "conduit:cleanup_lock"
CLEANUP_LOCK_TTL = 300  # 5 minutes max for cleanup to run


class CleanupService:
    """Periodically deletes old job history and associated artifacts."""

    def __init__(
        self,
        redis_client: Any | None = None,
        retention_days: int = 30,
        interval_hours: int = 1,
    ) -> None:
        self._redis = redis_client
        self._retention_days = retention_days
        self._interval_seconds = interval_hours * 3600
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the cleanup background task."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"Cleanup service started "
            f"(retention={self._retention_days}d, "
            f"interval={self._interval_seconds // 3600}h)"
        )

    async def stop(self) -> None:
        """Stop the cleanup background task."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Cleanup service stopped")

    async def _loop(self) -> None:
        """Run cleanup on interval."""
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self._run_cleanup()

    async def _run_cleanup(self) -> None:
        """Acquire lock and delete old records."""
        acquired = False

        if self._redis:
            try:
                acquired = await self._redis.set(
                    CLEANUP_LOCK_KEY, "1", nx=True, ex=CLEANUP_LOCK_TTL
                )
            except Exception:
                acquired = False
        else:
            # No Redis = single instance, always run
            acquired = True

        if not acquired:
            return

        try:
            db = get_database()
            async with db.session() as session:
                repo = JobRepository(session)
                deleted = await repo.cleanup_old_records(
                    retention_days=self._retention_days
                )
                if deleted > 0:
                    logger.info(
                        f"Cleanup: deleted {deleted} job records "
                        f"older than {self._retention_days} days"
                    )
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
        finally:
            if self._redis:
                try:
                    await self._redis.delete(CLEANUP_LOCK_KEY)
                except Exception:
                    pass
