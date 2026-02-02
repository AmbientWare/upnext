"""Redis backend that persists events to Redis storage."""

import logging
from typing import Any

from shared.models import Job

from conduit.engine.backend.base import BaseBackend
from conduit.engine.database import RedisStorage

logger = logging.getLogger(__name__)


class RedisBackend(BaseBackend):
    """
    Backend that persists job events to Redis.

    Used for self-hosted deployments where events are stored in Redis
    instead of being sent to the Conduit API.

    Example:
        client = redis.asyncio.from_url("redis://localhost:6379")
        backend = RedisBackend(client)
        await backend.connect("worker_1", "my-worker")

        # StatusBuffer flushes events here
        await backend.batch_send(events)
    """

    def __init__(self, client: Any) -> None:
        """
        Initialize Redis backend.

        Args:
            client: Redis-compatible async client (redis.asyncio or fakeredis)
        """
        self._client = client
        self._storage: RedisStorage | None = None
        self._connected = False
        self._worker_id: str | None = None

    @property
    def is_connected(self) -> bool:
        """Check if backend is connected."""
        return self._connected

    async def connect(
        self,
        worker_id: str,
        worker_name: str,
        *,
        functions: list[str] | None = None,
        function_definitions: list[dict[str, Any]] | None = None,
        concurrency: int = 10,
    ) -> bool:
        """
        Initialize the storage connection.

        Args:
            worker_id: Unique worker identifier
            worker_name: Human-readable worker name
            functions: List of function names (unused Redis)
            function_definitions: Function definitions (unused Redis)
            concurrency: Worker concurrency (unused Redis)

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self._worker_id = worker_id
            self._storage = RedisStorage(self._client)
            self._connected = True
            logger.debug("Redis backend connected")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect Redis backend: {e}")
            return False

    async def disconnect(self) -> None:
        """Close the storage connection."""
        self._connected = False
        logger.debug("Redis backend disconnected")

    async def heartbeat(
        self,
        worker_id: str,
        active_jobs: int = 0,
        jobs_processed: int = 0,
        jobs_failed: int = 0,
        queued_jobs: int = 0,
    ) -> bool:
        """
        Heartbeat (no-op for Redis backend).

        Redis storage doesn't need heartbeats.
        """
        return self._connected

    async def batch_send(self, events: list[Any]) -> None:
        """
        Process a batch of status events.

        Delegates to RedisStorage.batch_send().

        Args:
            events: List of StatusEvent objects to persist
        """
        if not self._connected or not self._storage:
            return

        await self._storage.batch_send(events)

    async def job_started(
        self,
        job: Job,
        *,
        worker_id: str | None = None,
    ) -> None:
        """Record that a job has started."""
        if not self._connected or not self._storage:
            return

        await self._storage.record_started(
            job_id=job.id,
            function=job.function,
            worker_id=worker_id or self._worker_id or "",
            attempt=job.attempts,
            max_retries=job.max_retries,
            kwargs=job.kwargs,
            metadata=job.metadata or {},
        )

    async def job_completed(
        self,
        job: Job,
        result: Any = None,
        duration_ms: float | None = None,
    ) -> None:
        """Record that a job completed successfully."""
        if not self._connected or not self._storage:
            return

        await self._storage.record_completed(
            job_id=job.id,
            result=result,
            duration_ms=int(duration_ms or 0),
        )

    async def job_failed(
        self,
        job: Job,
        error: str,
        traceback: str | None = None,
        will_retry: bool = False,
    ) -> None:
        """Record that a job failed."""
        if not self._connected or not self._storage:
            return

        await self._storage.record_failed(
            job_id=job.id,
            error=error,
            error_traceback=traceback,
            duration_ms=0,
        )
