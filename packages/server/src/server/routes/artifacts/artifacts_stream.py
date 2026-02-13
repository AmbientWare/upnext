import asyncio
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from shared.keys import ARTIFACT_EVENTS_STREAM

from server.routes.artifacts.artifacts_utils import parse_artifact_stream_event
from server.services.redis import get_redis

logger = logging.getLogger(__name__)

artifact_stream_router = APIRouter(tags=["artifacts"])


@artifact_stream_router.get("/stream")
async def stream_job_artifacts(job_id: str, request: Request) -> StreamingResponse:
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
                    {ARTIFACT_EVENTS_STREAM: last_id},
                    count=200,
                    block=15_000,
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
                        if parsed.job_id != job_id:
                            continue
                        yield f"data: {parsed.model_dump_json()}\n\n"

        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
