"""Artifact creation for job outputs."""

import asyncio
import logging
from typing import Any, Literal, overload

import aiohttp
from pydantic import TypeAdapter
from shared.artifacts import ArtifactType
from shared.schemas import ArtifactCreateResponse, ErrorResponse
from upnext.config import get_settings
from upnext.sdk.context import get_current_context

logger = logging.getLogger(__name__)


ArtifactCreateResult = ArtifactCreateResponse | ErrorResponse

_artifact_create_response_adapter = TypeAdapter(ArtifactCreateResponse)
_error_response_adapter = TypeAdapter(ErrorResponse)


# TEXT: plain string
@overload
async def create_artifact(
    name: str,
    data: str,
    artifact_type: Literal[ArtifactType.TEXT],
) -> ArtifactCreateResult: ...


# JSON: dict or list (default)
@overload
async def create_artifact(
    name: str,
    data: dict[str, Any] | list[Any],
    artifact_type: Literal[ArtifactType.JSON] = ...,
) -> ArtifactCreateResult: ...


# IMAGE: base64 string
@overload
async def create_artifact(
    name: str,
    data: str,
    artifact_type: Literal[
        ArtifactType.PNG,
        ArtifactType.JPEG,
        ArtifactType.WEBP,
        ArtifactType.GIF,
        ArtifactType.SVG,
    ],
) -> ArtifactCreateResult: ...


# FILE: base64 string
@overload
async def create_artifact(
    name: str,
    data: str,
    artifact_type: Literal[
        ArtifactType.PDF,
        ArtifactType.CSV,
        ArtifactType.XML,
        ArtifactType.HTML,
        ArtifactType.BINARY,
    ],
) -> ArtifactCreateResult: ...


async def create_artifact(
    name: str,
    data: str | dict[str, Any] | list[Any],
    artifact_type: ArtifactType = ArtifactType.JSON,
) -> ArtifactCreateResult:
    """
    Create an artifact for the current job.

    Artifacts are stored outputs like text, JSON data, images, or files
    that can be retrieved later via the API or dashboard.

    Must be called from within a task (requires current context).

    Args:
        name: Artifact name (e.g., "output.json", "result.txt")
        data: Artifact data:
            - TEXT/JSON: str or dict/list
            - Images (PNG, JPEG, etc.): str (base64-encoded)
            - Files (PDF, CSV, etc.): str (base64-encoded)
        artifact_type: Type of artifact (default: ArtifactType.JSON)

    Returns:
        ArtifactCreateResult:
        - Immediate create: `shared.schemas.ArtifactResponse`
        - Queued create: `shared.schemas.ArtifactQueuedResponse`
        - Error: `shared.schemas.ErrorResponse`

    Example:
        from upnext import create_artifact, ArtifactType

        @worker.task
        async def process_data():
            # JSON artifact (default)
            await create_artifact("result", {"score": 0.95})

            # Text artifact
            await create_artifact("summary.txt", "Processing complete", ArtifactType.TEXT)

            # Image artifact (base64)
            await create_artifact("chart.png", base64_png, ArtifactType.PNG)

            # File artifact (base64)
            await create_artifact("report.pdf", base64_pdf, ArtifactType.PDF)
    """
    ctx = get_current_context()
    settings = get_settings()
    url = f"{settings.url}/api/v1/jobs/{ctx.job_id}/artifacts"

    payload = {
        "name": name,
        "type": artifact_type.value,
        "data": data,
    }

    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status in (200, 202):
                    result = await resp.json()
                    if resp.status == 200:
                        logger.debug(f"Created artifact '{name}' for job {ctx.job_id}")
                    else:
                        logger.debug(f"Queued artifact '{name}' for job {ctx.job_id}")
                    return _artifact_create_response_adapter.validate_python(result)
                else:
                    text = await resp.text()
                    logger.warning(f"Failed to create artifact: {resp.status} {text}")
                    try:
                        payload = await resp.json()
                    except Exception:
                        payload = None
                    if isinstance(payload, dict):
                        try:
                            return _error_response_adapter.validate_python(payload)
                        except Exception:
                            pass
                    return ErrorResponse(detail=text or f"HTTP {resp.status}")
    except Exception as e:
        logger.warning(f"Error creating artifact: {e}")
        return ErrorResponse(detail=str(e))


# Sync overloads
@overload
def create_artifact_sync(
    name: str,
    data: str,
    artifact_type: Literal[ArtifactType.TEXT],
) -> ArtifactCreateResult: ...


@overload
def create_artifact_sync(
    name: str,
    data: dict[str, Any] | list[Any],
    artifact_type: Literal[ArtifactType.JSON] = ...,
) -> ArtifactCreateResult: ...


@overload
def create_artifact_sync(
    name: str,
    data: str,
    artifact_type: Literal[
        ArtifactType.PNG,
        ArtifactType.JPEG,
        ArtifactType.WEBP,
        ArtifactType.GIF,
        ArtifactType.SVG,
    ],
) -> ArtifactCreateResult: ...


@overload
def create_artifact_sync(
    name: str,
    data: str,
    artifact_type: Literal[
        ArtifactType.PDF,
        ArtifactType.CSV,
        ArtifactType.XML,
        ArtifactType.HTML,
        ArtifactType.BINARY,
    ],
) -> ArtifactCreateResult: ...


def create_artifact_sync(
    name: str,
    data: str | dict[str, Any] | list[Any],
    artifact_type: ArtifactType = ArtifactType.JSON,
) -> ArtifactCreateResult:
    """
    Sync version of create_artifact for use in sync tasks.

    See create_artifact for full documentation.

    Example:
        from upnext import create_artifact_sync, ArtifactType

        @worker.task(executor="process")
        def process_data():
            create_artifact_sync("result", {"score": 0.95})
    """
    return asyncio.run(create_artifact(name, data, artifact_type))  # type: ignore[arg-type]
