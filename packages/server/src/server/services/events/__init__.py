"""Event stream service components."""

from server.services.events.processing import process_event
from server.services.events.subscriber import StreamSubscriber, StreamSubscriberConfig
from shared.contracts import EventProcessingStats

_subscriber_instance: StreamSubscriber | None = None


def register_subscriber(subscriber: StreamSubscriber) -> None:
    """Store the active subscriber for health endpoint access."""
    global _subscriber_instance
    _subscriber_instance = subscriber


def get_event_processing_stats() -> EventProcessingStats:
    """Return event processing discard counters from the active subscriber."""
    if _subscriber_instance is None:
        return EventProcessingStats()
    try:
        return _subscriber_instance.discarded_event_stats
    except Exception:
        return EventProcessingStats()


__all__ = [
    "process_event",
    "StreamSubscriber",
    "StreamSubscriberConfig",
    "register_subscriber",
    "get_event_processing_stats",
]
