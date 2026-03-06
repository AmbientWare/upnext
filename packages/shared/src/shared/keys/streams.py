"""Redis stream/channel keys used for event distribution."""

from shared.keys.namespace import WORKSPACE_NAMESPACE_PREFIX, scoped_key


def status_events_stream_key(*, workspace_id: str | None = None) -> str:
    return scoped_key("status", "events", workspace_id=workspace_id)


def api_requests_stream_key(*, workspace_id: str | None = None) -> str:
    return scoped_key("api", "requests", workspace_id=workspace_id)


def artifact_events_stream_key(*, workspace_id: str | None = None) -> str:
    return scoped_key("artifacts", "events", workspace_id=workspace_id)


def status_events_pubsub_channel(*, workspace_id: str | None = None) -> str:
    return scoped_key("status", "events", "pubsub", workspace_id=workspace_id)


def status_events_stream_pattern() -> str:
    return f"{WORKSPACE_NAMESPACE_PREFIX}:*:status:events"


EVENTS_STREAM = status_events_stream_key()
API_REQUESTS_STREAM = api_requests_stream_key()
ARTIFACT_EVENTS_STREAM = artifact_events_stream_key()
EVENTS_PUBSUB_CHANNEL = status_events_pubsub_channel()


__all__ = [
    "EVENTS_STREAM",
    "API_REQUESTS_STREAM",
    "ARTIFACT_EVENTS_STREAM",
    "EVENTS_PUBSUB_CHANNEL",
    "status_events_stream_key",
    "api_requests_stream_key",
    "artifact_events_stream_key",
    "status_events_pubsub_channel",
    "status_events_stream_pattern",
]
