"""Redis stream/channel keys used for event distribution."""

EVENTS_STREAM = "upnext:status:events"
API_REQUESTS_STREAM = "upnext:api:requests"
ARTIFACT_EVENTS_STREAM = "upnext:artifacts:events"
EVENTS_PUBSUB_CHANNEL = "upnext:status:events:pubsub"


__all__ = [
    "EVENTS_STREAM",
    "API_REQUESTS_STREAM",
    "ARTIFACT_EVENTS_STREAM",
    "EVENTS_PUBSUB_CHANNEL",
]
