"""Events routes."""

from fastapi import APIRouter
from shared.events import (
    BatchEventRequest,
    BatchEventResponse,
    EventRequest,
    EventResponse,
)

from server.routes.events.events_root import (
    events_root_router,
    ingest_batch,
    ingest_event,
)
from server.routes.events.events_stream import events_stream_router, stream_events

EVENTS_PREFIX = "/events"

router = APIRouter(tags=["events"])
router.include_router(events_root_router, prefix=EVENTS_PREFIX)
router.include_router(events_stream_router, prefix=EVENTS_PREFIX)

__all__ = [
    "BatchEventRequest",
    "BatchEventResponse",
    "EVENTS_PREFIX",
    "EventRequest",
    "EventResponse",
    "events_root_router",
    "events_stream_router",
    "ingest_batch",
    "ingest_event",
    "router",
    "stream_events",
]
