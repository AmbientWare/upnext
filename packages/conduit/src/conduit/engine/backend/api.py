"""
Job backend for reporting events to Conduit API.

When CONDUIT_URL and CONDUIT_API_KEY are set, the worker reports
job events to the hosted Conduit API for history, analytics, and dashboard.
"""

import asyncio
import json
import logging
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp
from shared.models import Job

from conduit.config import get_settings
from conduit.engine.backend.base import BaseBackend

logger = logging.getLogger(__name__)


@dataclass
class ApiBackendConfig:
    """Configuration for the job backend."""

    url: str
    api_key: str | None = None  # Optional for self-hosted
    timeout: float = 10.0
    retry_attempts: int = 3
    retry_delay: float = 1.0


class ApiBackend(BaseBackend):
    """
    Reports job events to the Conduit API backend.

    This is the bridge between the worker and your hosted dashboard.
    Events are sent asynchronously and failures don't block job execution.
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
        Connect to the Conduit API and validate credentials.

        Performs a health check and registers the worker.

        Args:
            worker_id: Unique worker identifier
            worker_name: Human-readable worker name
            functions: List of function names this worker handles
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

    async def job_started(
        self,
        job: Job,
        *,
        worker_id: str | None = None,
    ) -> None:
        """Report that a job has started."""
        if not self._connected:
            return

        await self._send_event(
            "job.started",
            {
                "job_id": job.id,
                "function": job.function,
                "kwargs": job.kwargs,
                "attempt": job.attempts,
                "max_retries": job.max_retries,
                "worker_id": worker_id or self._worker_id,
                "started_at": datetime.now(UTC).isoformat(),
            },
        )

    async def job_completed(
        self,
        job: Job,
        result: Any = None,
        duration_ms: float | None = None,
    ) -> None:
        """Report that a job completed successfully."""
        if not self._connected:
            return

        await self._send_event(
            "job.completed",
            {
                "job_id": job.id,
                "function": job.function,
                "result": self._serialize_result(result),
                "duration_ms": duration_ms,
                "attempt": job.attempts,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )

    async def job_failed(
        self,
        job: Job,
        error: str,
        traceback: str | None = None,
        will_retry: bool = False,
    ) -> None:
        """Report that a job failed."""
        if not self._connected:
            return

        await self._send_event(
            "job.failed",
            {
                "job_id": job.id,
                "function": job.function,
                "error": error,
                "traceback": traceback,
                "attempt": job.attempts,
                "max_retries": job.max_retries,
                "will_retry": will_retry,
                "failed_at": datetime.now(UTC).isoformat(),
            },
        )

    async def job_retrying(
        self,
        job: Job,
        error: str,
        delay: float,
        next_attempt: int,
    ) -> None:
        """Report that a job is being retried."""
        if not self._connected:
            return

        await self._send_event(
            "job.retrying",
            {
                "job_id": job.id,
                "function": job.function,
                "error": error,
                "delay_seconds": delay,
                "current_attempt": job.attempts,
                "next_attempt": next_attempt,
                "retry_at": datetime.now(UTC).isoformat(),
            },
        )

    async def job_progress(
        self,
        job_id: str,
        progress: float,
        message: str | None = None,
    ) -> None:
        """Report job progress update."""
        if not self._connected:
            return

        await self._send_event(
            "job.progress",
            {
                "job_id": job_id,
                "progress": progress,
                "message": message,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    async def job_checkpoint(
        self,
        job_id: str,
        state: dict[str, Any],
    ) -> None:
        """Report job checkpoint for resumption after failures."""
        if not self._connected:
            return

        await self._send_event(
            "job.checkpoint",
            {
                "job_id": job_id,
                "state": state,
                "checkpointed_at": datetime.now(UTC).isoformat(),
            },
        )

    async def artifact(
        self,
        job_id: str,
        name: str,
        data: bytes | str,
        content_type: str = "application/octet-stream",
    ) -> str | None:
        """
        Upload an artifact for a job.

        Returns the artifact URL if successful.
        """
        if not self._connected or not self._session:
            return None

        try:
            # Prepare multipart data
            form = aiohttp.FormData()
            form.add_field("job_id", job_id)
            form.add_field("name", name)
            form.add_field(
                "file",
                data if isinstance(data, bytes) else data.encode(),
                filename=name,
                content_type=content_type,
            )

            async with self._session.post(
                "/api/v1/artifacts",
                data=form,
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("url")
                else:
                    logger.warning(f"Failed to upload artifact: {resp.status}")
                    return None

        except Exception as e:
            logger.debug(f"Artifact upload failed: {e}")
            return None

    async def log(
        self,
        job_id: str,
        level: str,
        message: str,
        **extra: Any,
    ) -> None:
        """Send a log entry for a job."""
        if not self._connected:
            return

        await self._send_event(
            "job.log",
            {
                "job_id": job_id,
                "level": level,
                "message": message,
                "extra": extra,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def _send_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Send an event to the API."""
        await self._send(
            "/api/v1/events",
            {
                "type": event_type,
                "data": data,
                "worker_id": self._worker_id,
            },
        )

    async def batch_send(self, events: list[Any]) -> None:
        """
        Send multiple status events in one API call.

        Used by StatusBuffer for efficient batched reporting.

        Args:
            events: List of StatusEvent objects to send
        """
        if not self._connected or not events:
            return

        # Convert StatusEvent objects to dicts
        event_dicts = []
        for event in events:
            event_dicts.append(
                {
                    "type": event.type,
                    "job_id": event.job_id,
                    "worker_id": event.worker_id,
                    "timestamp": event.timestamp,
                    "data": event.data,
                }
            )

        await self._send(
            "/api/v1/events/batch",
            {
                "events": event_dicts,
                "worker_id": self._worker_id,
            },
        )

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

    def _serialize_result(self, result: Any) -> Any:
        """Serialize a result for JSON transport."""
        if result is None:
            return None

        # Try direct JSON serialization
        try:
            json.dumps(result)
            return result
        except (TypeError, ValueError):
            # Fall back to string representation
            return str(result)


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
