"""Artifact creation for job outputs."""

import asyncio
import logging
from typing import Any, Literal, overload

import aiohttp
from shared.artifacts import ArtifactType

from conduit.config import get_settings
from conduit.sdk.context import get_current_context

logger = logging.getLogger(__name__)


# TEXT: plain string
@overload
async def create_artifact(
    name: str,
    data: str,
    artifact_type: Literal[ArtifactType.TEXT],
) -> dict[str, Any]: ...


# JSON: dict or list (default)
@overload
async def create_artifact(
    name: str,
    data: dict[str, Any] | list[Any],
    artifact_type: Literal[ArtifactType.JSON] = ...,
) -> dict[str, Any]: ...


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
) -> dict[str, Any]: ...


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
) -> dict[str, Any]: ...


async def create_artifact(
    name: str,
    data: str | dict[str, Any] | list[Any],
    artifact_type: ArtifactType = ArtifactType.JSON,
) -> dict[str, Any]:
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
        Dict with artifact info including 'id'

    Example:
        from conduit import create_artifact, ArtifactType

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
                if resp.status == 200:
                    result = await resp.json()
                    logger.debug(f"Created artifact '{name}' for job {ctx.job_id}")
                    return result
                else:
                    text = await resp.text()
                    logger.warning(f"Failed to create artifact: {resp.status} {text}")
                    return {"error": text, "status": resp.status}
    except Exception as e:
        logger.warning(f"Error creating artifact: {e}")
        return {"error": str(e)}


# Sync overloads
@overload
def create_artifact_sync(
    name: str,
    data: str,
    artifact_type: Literal[ArtifactType.TEXT],
) -> dict[str, Any]: ...


@overload
def create_artifact_sync(
    name: str,
    data: dict[str, Any] | list[Any],
    artifact_type: Literal[ArtifactType.JSON] = ...,
) -> dict[str, Any]: ...


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
) -> dict[str, Any]: ...


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
) -> dict[str, Any]: ...


def create_artifact_sync(
    name: str,
    data: str | dict[str, Any] | list[Any],
    artifact_type: ArtifactType = ArtifactType.JSON,
) -> dict[str, Any]:
    """
    Sync version of create_artifact for use in sync tasks.

    See create_artifact for full documentation.

    Example:
        from conduit import create_artifact_sync, ArtifactType

        @worker.task(executor="process")
        def process_data():
            create_artifact_sync("result", {"score": 0.95})
    """
    return asyncio.run(create_artifact(name, data, artifact_type))  # type: ignore[arg-type]
