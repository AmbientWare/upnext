"""
API backend for worker registration with Conduit server.

Workers register and send heartbeats to the server. Job events are now
handled via Redis streams (StatusPublisher writes, server subscribes).
"""

import asyncio
import logging
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp

from conduit.config import get_settings
from conduit.engine.backend.base import BaseBackend

logger = logging.getLogger(__name__)


@dataclass
class ApiBackendConfig:
    """Configuration for the API backend."""

    url: str
    api_key: str | None = None  # Optional for self-hosted
    timeout: float = 10.0
    retry_attempts: int = 3
    retry_delay: float = 1.0


class ApiBackend(BaseBackend):
    """
    Handles worker registration and heartbeats with the Conduit API.

    Job events are written to Redis streams by StatusPublisher and consumed
    by the server's stream subscriber - no longer sent via HTTP.
    """

    def __init__(self, config: ApiBackendConfig) -> None:
        self._config = config
        self._session: Any = None  # aiohttp.ClientSession
        self._connected = False
        self._worker_id: str | None = None
        self._worker_name: str | None = None

    @property
    def is_connected(self) -> bool:
        """Check if API backend is connected to the API."""
        return self._connected

    async def connect(
        self,
        worker_id: str,
        worker_name: str,
        *,
        functions: list[str] | None = None,
        function_definitions: list[dict[str, Any]] | None = None,
        concurrency: int = 10,
        hostname: str | None = None,
        version: str | None = None,
    ) -> bool:
        """
        Connect to the Conduit API and register the worker.

        Performs a health check and registers the worker.

        Args:
            worker_id: Unique worker identifier
            worker_name: Human-readable worker name
            functions: List of function names this worker handles
            function_definitions: Detailed function definitions
            concurrency: Worker concurrency level
            hostname: Worker hostname
            version: Worker/app version

        Returns:
            True if connection successful, False otherwise
        """
        self._worker_id = worker_id
        self._worker_name = worker_name

        try:
            # Close existing session if any (happens during re-registration)
            if self._session:
                try:
                    await self._session.close()
                except Exception:
                    pass
                self._session = None

            headers = {
                "Content-Type": "application/json",
                "User-Agent": "conduit-worker/0.1.0",
            }
            if self._config.api_key:
                headers["Authorization"] = f"Bearer {self._config.api_key}"

            self._session = aiohttp.ClientSession(
                base_url=self._config.url,
                timeout=aiohttp.ClientTimeout(total=self._config.timeout),
                headers=headers,
            )

            # Health check
            async with self._session.get("/health") as resp:
                if resp.status != 200:
                    logger.warning(f"Conduit API health check failed: {resp.status}")
                    await self._session.close()
                    return False

            actual_hostname = hostname or socket.gethostname()

            # Register worker with full info
            result = await self._send(
                "/api/v1/workers/register",
                {
                    "worker_id": worker_id,
                    "worker_name": worker_name,
                    "started_at": datetime.now(UTC).isoformat(),
                    "functions": functions or [],
                    "function_definitions": function_definitions or [],
                    "concurrency": concurrency,
                    "hostname": actual_hostname,
                    "version": version or "0.1.0",
                },
            )

            if result is None:
                logger.warning("Worker registration failed")
                await self._session.close()
                self._session = None
                return False

            self._connected = True
            logger.debug("Connected to Conduit API")
            return True

        except Exception as e:
            logger.warning(f"Failed to connect to Conduit API: {e}")
            if self._session:
                await self._session.close()
                self._session = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from the API."""
        if self._session:
            # Deregister worker
            if self._connected and self._worker_id:
                try:
                    await self._send(
                        "/api/v1/workers/deregister",
                        {"worker_id": self._worker_id},
                    )
                except Exception:
                    pass  # Best effort

            await self._session.close()
            self._session = None
            self._connected = False

    async def heartbeat(
        self,
        worker_id: str,
        active_jobs: int = 0,
        jobs_processed: int = 0,
        jobs_failed: int = 0,
        queued_jobs: int = 0,
    ) -> bool:
        """Send heartbeat to keep worker registered.

        Returns:
            True if heartbeat succeeded, False if worker needs to re-register.
        """
        if not self._connected:
            return False

        result = await self._send(
            "/api/v1/workers/heartbeat",
            {
                "worker_id": worker_id,
                "active_jobs": active_jobs,
                "jobs_processed": jobs_processed,
                "jobs_failed": jobs_failed,
                "queued_jobs": queued_jobs,
            },
        )
        return result is not None

    async def _send(
        self,
        endpoint: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Send data to the API with retries."""
        if not self._session:
            return None

        for attempt in range(self._config.retry_attempts):
            try:
                async with self._session.post(endpoint, json=data) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status >= 500:
                        # Server error, retry
                        if attempt < self._config.retry_attempts - 1:
                            await asyncio.sleep(self._config.retry_delay)
                            continue
                    else:
                        # Client error, don't retry
                        logger.debug(f"API request failed: {resp.status} {endpoint}")
                        return None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt < self._config.retry_attempts - 1:
                    await asyncio.sleep(self._config.retry_delay)
                else:
                    logger.debug(f"API request failed after retries: {e}")

        return None


def get_api_backend_config() -> ApiBackendConfig:
    """
    Get API backend configuration.

    Uses conduit.config.settings which defaults to localhost for development.
    Override with CONDUIT_URL environment variable for cloud/production.
    """
    settings = get_settings()
    return ApiBackendConfig(url=settings.url, api_key=settings.api_key)


async def create_api_backend() -> ApiBackend:
    """
    Create an API backend instance.

    Always returns an ApiBackend - defaults to localhost in development.
    The backend will gracefully handle connection failures.
    """
    config = get_api_backend_config()
    return ApiBackend(config)
