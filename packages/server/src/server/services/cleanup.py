"""Periodic cleanup service for old job history and artifacts.

Runs on a configurable interval, using a Redis distributed lock
so only one server instance performs cleanup at a time.
"""

import asyncio
import logging
import random
from typing import Any
from uuid import uuid4

from server.db.repository import ArtifactRepository, JobRepository
from server.db.session import get_database
from server.services.artifact_storage import get_artifact_storage

logger = logging.getLogger(__name__)

CLEANUP_LOCK_KEY = "upnext:cleanup_lock"
CLEANUP_LOCK_TTL = 300  # 5 minutes max for cleanup to run
RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""


class CleanupService:
    """Periodically deletes old job history and associated artifacts."""

    def __init__(
        self,
        redis_client: Any | None = None,
        retention_days: int = 30,
        interval_hours: int = 1,
        pending_retention_hours: int = 24,
        pending_promote_batch: int = 500,
        pending_promote_max_loops: int = 20,
        startup_jitter_seconds: float = 30.0,
    ) -> None:
        self._redis = redis_client
        self._retention_days = retention_days
        self._interval_seconds = interval_hours * 3600
        self._pending_retention_hours = pending_retention_hours
        self._pending_promote_batch = pending_promote_batch
        self._pending_promote_max_loops = pending_promote_max_loops
        self._startup_jitter_seconds = max(0.0, startup_jitter_seconds)
        self._task: asyncio.Task[None] | None = None

    async def _delete_storage_objects(
        self, storage_refs: set[tuple[str, str]]
    ) -> int:
        """Best-effort deletion of stored artifact content."""
        if not storage_refs:
            return 0

        deleted_count = 0
        for backend_name, storage_key in storage_refs:
            if not storage_key:
                continue
            try:
                storage = get_artifact_storage(backend_name)
                await storage.delete(key=storage_key)
                deleted_count += 1
            except Exception as exc:
                logger.debug(
                    "Cleanup: failed deleting artifact storage object backend=%s key=%s: %s",
                    backend_name,
                    storage_key,
                    exc,
                )
        return deleted_count

    async def start(self) -> None:
        """Start the cleanup background task."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"Cleanup service started "
            f"(retention={self._retention_days}d, "
            f"interval={self._interval_seconds // 3600}h, "
            f"pending_retention={self._pending_retention_hours}h, "
            f"startup_jitter={self._startup_jitter_seconds:.0f}s)"
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
        # Delay first cleanup run so restart waves do not stampede the lock.
        if self._startup_jitter_seconds > 0:
            await asyncio.sleep(random.uniform(0, self._startup_jitter_seconds))
        else:
            await asyncio.sleep(self._interval_seconds)

        while True:
            await self._run_cleanup()
            await asyncio.sleep(self._interval_seconds)

    async def _run_cleanup(self) -> None:
        """Acquire lock and delete old records."""
        acquired = False
        lock_token: str | None = None

        if self._redis:
            try:
                lock_token = uuid4().hex
                acquired = await self._redis.set(
                    CLEANUP_LOCK_KEY, lock_token, nx=True, ex=CLEANUP_LOCK_TTL
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
            stale_pending_rows = []
            old_artifact_rows = []
            deleted = 0
            promoted = 0
            expired_pending = 0
            async with db.session() as session:
                job_repo = JobRepository(session)
                artifact_repo = ArtifactRepository(session)

                # Reconcile pending artifacts in bounded batches.
                for _ in range(self._pending_promote_max_loops):
                    batch = await artifact_repo.promote_ready_pending(
                        limit=self._pending_promote_batch
                    )
                    promoted += batch
                    if batch < self._pending_promote_batch:
                        break

                stale_pending_rows = await artifact_repo.cleanup_stale_pending_with_rows(
                    retention_hours=self._pending_retention_hours
                )
                expired_pending = len(stale_pending_rows)

                old_job_ids = await job_repo.list_old_job_ids(
                    retention_days=self._retention_days
                )
                old_artifact_rows = await artifact_repo.list_by_job_ids(old_job_ids)
                deleted = await job_repo.delete_by_ids(old_job_ids)

                if promoted > 0:
                    logger.info(f"Cleanup: promoted {promoted} pending artifacts")
                if expired_pending > 0:
                    logger.info(
                        f"Cleanup: deleted {expired_pending} stale pending artifacts "
                        f"older than {self._pending_retention_hours} hours"
                    )
                if deleted > 0:
                    logger.info(
                        f"Cleanup: deleted {deleted} job records "
                        f"older than {self._retention_days} days"
                    )

            storage_refs = {
                (artifact.storage_backend, artifact.storage_key)
                for artifact in old_artifact_rows
                if artifact.storage_key
            } | {
                (pending.storage_backend, pending.storage_key)
                for pending in stale_pending_rows
                if pending.storage_key
            }
            storage_deleted = await self._delete_storage_objects(storage_refs)
            if storage_deleted > 0:
                logger.info(
                    "Cleanup: deleted %s artifact storage objects", storage_deleted
                )
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
        finally:
            if self._redis and acquired and lock_token:
                try:
                    await self._redis.eval(
                        RELEASE_LOCK_SCRIPT,
                        1,
                        CLEANUP_LOCK_KEY,
                        lock_token,
                    )
                except Exception:
                    pass
