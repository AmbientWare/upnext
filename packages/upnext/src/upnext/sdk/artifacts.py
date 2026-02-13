"""Artifact creation for job outputs."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, Literal, TypeVar, overload

from shared.artifacts import ArtifactType
from shared.contracts.artifacts import CreateArtifactRequest

from upnext.engine.backend_api import ArtifactCreateResult, get_backend_api
from upnext.sdk.context import get_current_context
from upnext.types import ArtifactData

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


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


@overload
async def create_artifact(
    name: str,
    data: ArtifactData,
    artifact_type: ArtifactType,
) -> ArtifactCreateResult: ...


async def create_artifact(
    name: str,
    data: ArtifactData,
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
        - Immediate create: `shared.contracts.artifacts.ArtifactResponse`
        - Queued create: `shared.contracts.artifacts.ArtifactQueuedResponse`
        - Error: `shared.contracts.artifacts.ErrorResponse`

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

    payload = CreateArtifactRequest(
        name=name,
        type=artifact_type,
        data=data,
    )

    api = get_backend_api()
    return await api.create_artifact(job_id=ctx.job_id, payload=payload)


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


@overload
def create_artifact_sync(
    name: str,
    data: ArtifactData,
    artifact_type: ArtifactType,
) -> ArtifactCreateResult: ...


def create_artifact_sync(
    name: str,
    data: ArtifactData,
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
    return _run_sync(create_artifact(name, data, artifact_type))


def _run_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise RuntimeError(
        "create_artifact_sync cannot run inside an active event loop; "
        "use 'await create_artifact(...)' instead."
    )
