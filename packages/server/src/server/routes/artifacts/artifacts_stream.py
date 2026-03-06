import asyncio
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from shared.contracts import (
    ArtifactCreateResponse,
    ArtifactListResponse,
    ArtifactQueuedResponse,
    CreateArtifactRequest,
    ErrorResponse,
)
from shared.keys import artifact_events_stream_key

import server.routes.artifacts.artifacts_root as artifacts_root_route
from server.auth import require_auth_scope
from server.backends.service import BackendService
from server.routes.artifacts.artifacts_utils import parse_artifact_stream_event
from server.routes.depends import require_backend
from server.routes.sse import SSE_BLOCK_MS, SSE_HEADERS, SSE_READ_COUNT
from server.runtime_scope import AuthScope
from server.services.redis import get_redis

logger = logging.getLogger(__name__)

artifact_stream_router = APIRouter(tags=["artifacts"])


@artifact_stream_router.post(
    "",
    response_model=ArtifactCreateResponse,
    responses={
        202: {
            "model": ArtifactQueuedResponse,
            "description": "Artifact queued until the job row is available.",
        },
        503: {"model": ErrorResponse, "description": "Backend not available."},
    },
)
async def create_job_artifact(
    job_id: str,
    request: CreateArtifactRequest,
    response: Response,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> ArtifactCreateResponse:
    """Create an artifact for a specific job (job-scoped path)."""
    return await artifacts_root_route.create_artifact(
        job_id, request, response, scope=scope, backend=backend
    )


@artifact_stream_router.get("", response_model=ArtifactListResponse)
async def list_job_artifacts(
    job_id: str,
    scope: AuthScope = Depends(require_auth_scope),
    backend: BackendService = Depends(require_backend),
) -> ArtifactListResponse:
    """List artifacts for a specific job (job-scoped path)."""
    return await artifacts_root_route.list_artifacts(
        job_id, scope=scope, backend=backend
    )


@artifact_stream_router.get("/stream")
async def stream_job_artifacts(
    job_id: str,
    request: Request,
    scope: AuthScope = Depends(require_auth_scope),
) -> StreamingResponse:
    """Stream artifact lifecycle events for a specific job via SSE."""
    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    async def event_stream() -> AsyncGenerator[str, None]:
        last_id = "$"
        try:
            yield "event: open\ndata: connected\n\n"
            while True:
                if await request.is_disconnected():
                    break

                result = await redis_client.xread(
                    {
                        artifact_events_stream_key(
                            workspace_id=scope.workspace_id
                        ): last_id
                    },
                    count=SSE_READ_COUNT,
                    block=SSE_BLOCK_MS,
                )
                if not result:
                    yield ": keep-alive\n\n"
                    continue

                for _stream_name, entries in result:
                    for event_id, row in entries:
                        event_id_str = str(event_id)
                        last_id = event_id_str
                        parsed = parse_artifact_stream_event(event_id_str, row)
                        if parsed is None:
                            continue
                        if parsed.workspace_id != scope.workspace_id:
                            continue
                        if parsed.job_id != job_id:
                            continue
                        yield f"data: {parsed.model_dump_json()}\n\n"

        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Artifact stream error: %s", exc)
            yield 'event: error\ndata: {"error": "stream disconnected"}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
