"""Redis stream/channel keys used for event distribution."""

from shared.keys.namespace import scoped_key


def status_events_stream_key(*, deployment_id: str | None = None) -> str:
    return scoped_key("status", "events", deployment_id=deployment_id)


def api_requests_stream_key(*, deployment_id: str | None = None) -> str:
    return scoped_key("api", "requests", deployment_id=deployment_id)


def artifact_events_stream_key(*, deployment_id: str | None = None) -> str:
    return scoped_key("artifacts", "events", deployment_id=deployment_id)


def status_events_pubsub_channel(*, deployment_id: str | None = None) -> str:
    return scoped_key("status", "events", "pubsub", deployment_id=deployment_id)


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
]
