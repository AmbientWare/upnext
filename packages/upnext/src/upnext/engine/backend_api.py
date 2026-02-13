"""Backend API for UpNext."""

import logging
from typing import Any, Self

import aiohttp
from pydantic import TypeAdapter
from shared.contracts.artifacts import (
    ArtifactCreateResponse,
    CreateArtifactRequest,
    ErrorResponse,
)

from upnext.config import get_settings

logger = logging.getLogger(__name__)

ArtifactCreateResult = ArtifactCreateResponse | ErrorResponse

_artifact_create_response_adapter = TypeAdapter(ArtifactCreateResponse)
_error_response_adapter = TypeAdapter(ErrorResponse)
_backend_api_singleton: "BackendAPI | None" = None


class BackendAPI:
    """Backend API for UpNext."""

    def __init__(self) -> None:
        """Initialize the backend API."""
        settings = get_settings()
        headers = {
            "Content-Type": "application/json",
        }
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        self._headers = headers
        self._session: aiohttp.ClientSession | None = None
        self._base_url = f"{settings.url.rstrip('/')}/api/v1"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        # Keep pooled connection(s) alive across calls.
        return None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or bool(getattr(self._session, "closed", False)):
            self._session = aiohttp.ClientSession(headers=self._headers)
        return self._session

    async def close(self) -> None:
        session = self._session
        if session is None:
            return
        if not bool(getattr(session, "closed", False)):
            await session.close()
        self._session = None

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        session = await self._ensure_session()
        return await session.request(method, url, **kwargs)

    async def create_artifact(
        self, job_id: str, payload: CreateArtifactRequest
    ) -> ArtifactCreateResult:
        url = f"{self._base_url}/jobs/{job_id}/artifacts"
        session = await self._ensure_session()
        try:
            async with session.post(
                url,
                json=payload.model_dump(mode="json"),
            ) as resp:
                if resp.status in (200, 202):
                    result = await resp.json()
                    if resp.status == 200:
                        logger.debug(
                            "Created artifact '%s' for job %s",
                            payload.name,
                            job_id,
                        )
                    else:
                        logger.debug(
                            "Queued artifact '%s' for job %s",
                            payload.name,
                            job_id,
                        )
                    return _artifact_create_response_adapter.validate_python(result)

                text = await resp.text()
                logger.warning("Failed to create artifact: %s %s", resp.status, text)
                try:
                    resp_payload = await resp.json()
                except Exception:
                    resp_payload = None

                if isinstance(resp_payload, dict):
                    try:
                        return _error_response_adapter.validate_python(resp_payload)
                    except Exception:
                        pass

                return ErrorResponse(detail=text or f"HTTP {resp.status}")

        except Exception as exc:
            logger.warning("Error creating artifact: %s", exc)
            return ErrorResponse(detail=str(exc))


def get_backend_api() -> BackendAPI:
    """Get shared backend API client with persistent connection pooling."""
    global _backend_api_singleton
    if _backend_api_singleton is None:
        _backend_api_singleton = BackendAPI()
    return _backend_api_singleton


async def close_backend_api() -> None:
    """Close shared backend API client resources."""
    global _backend_api_singleton
    if _backend_api_singleton is None:
        return
    await _backend_api_singleton.close()
    _backend_api_singleton = None
