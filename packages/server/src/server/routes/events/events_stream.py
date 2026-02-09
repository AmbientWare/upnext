"""Event ingestion routes."""

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from shared.events import (
    EVENTS_PUBSUB_CHANNEL,
)

from server.services import get_redis

logger = logging.getLogger(__name__)

events_stream_router = APIRouter(tags=["events"])


@events_stream_router.get("/stream")
async def stream_events() -> StreamingResponse:
    """Stream job events via Server-Sent Events (SSE)."""
    try:
        redis_client = await get_redis()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(EVENTS_PUBSUB_CHANNEL)

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            yield "event: open\ndata: connected\n\n"
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=15.0,
                )
                if message and message.get("type") == "message":
                    data = message.get("data")
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield f"data: {data}\n\n"
                else:
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            pass

        finally:
            await pubsub.unsubscribe(EVENTS_PUBSUB_CHANNEL)
            await pubsub.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
