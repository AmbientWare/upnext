"""Base backend class for worker registration."""

from abc import ABC, abstractmethod
from typing import Any


class BaseBackend(ABC):
    """
    Abstract base class for worker registration backends.

    Handles worker registration and heartbeats with the Conduit server.
    Job events are written to Redis streams by StatusPublisher and consumed
    by the server's stream subscriber.
    """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if backend is connected and ready."""
        ...

    @abstractmethod
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
        Connect/initialize the backend and register the worker.

        Returns:
            True if connection successful, False otherwise
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect and cleanup."""
        ...

    @abstractmethod
    async def heartbeat(
        self,
        worker_id: str,
        active_jobs: int = 0,
        jobs_processed: int = 0,
        jobs_failed: int = 0,
        queued_jobs: int = 0,
    ) -> bool:
        """
        Send heartbeat to keep worker registered.

        Returns:
            True if heartbeat succeeded, False otherwise.
        """
        ...
