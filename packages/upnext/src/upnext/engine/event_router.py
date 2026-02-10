"""Event router for pattern-based event delivery."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from shared.patterns import matches_event_pattern

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Represents an event in the system."""

    name: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str | None = None
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "event_id": self.event_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        """Create from dictionary."""
        return cls(
            name=d["name"],
            data=d["data"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            source=d.get("source"),
            event_id=d.get("event_id"),
        )


@dataclass
class EventDefinition:
    """Definition of an event."""

    pattern: str  # Event pattern (supports wildcards)
    handler: Callable[..., Any]
    name: str
    is_async: bool = True


class EventRouter:
    """
    Routes events to matching events using pattern matching.

    Supports glob-style wildcards:
    - "user.signup" matches only "user.signup"
    - "user.*" matches "user.signup", "user.login", etc.
    - "payment.**" matches "payment.success", "payment.failed.retry", etc.

    Example:
        router = EventRouter()

        @router.event("user.*")
        async def on_user_event(ctx, event):
            ...

        # Deliver events
        await router.deliver(Event(name="user.signup", data={"user_id": "123"}))
    """

    def __init__(self) -> None:
        self._events: list[EventDefinition] = []

    def register(
        self,
        pattern: str,
        handler: Callable[..., Any],
        *,
        name: str | None = None,
        is_async: bool = True,
    ) -> None:
        """
        Register an event handler for an event pattern.

        Args:
            pattern: Event name pattern (supports wildcards)
            handler: Function to call when event matches
            name: Event name (defaults to handler function name)
            is_async: Whether handler is async
        """
        event_def = EventDefinition(
            pattern=pattern,
            handler=handler,
            name=name or handler.__name__,
            is_async=is_async,
        )
        self._events.append(event_def)
        logger.debug(f"Registered event '{event_def.name}' for pattern '{pattern}'")

    def unregister(self, name: str) -> bool:
        """
        Unregister an event by name.

        Returns:
            True if event was found and removed
        """
        for i, event in enumerate(self._events):
            if event.name == name:
                self._events.pop(i)
                return True
        return False

    def match(self, event_name: str) -> list[EventDefinition]:
        """
        Find all events that match an event name.

        Args:
            event_name: Event name to match

        Returns:
            List of matching event definitions
        """
        matches = []
        for event in self._events:
            if matches_event_pattern(event_name, event.pattern):
                matches.append(event)
        return matches

    @property
    def events(self) -> list[EventDefinition]:
        """Get all registered events."""
        return self._events.copy()


# Global event router instance
_router: EventRouter | None = None


def get_event_router() -> EventRouter:
    """Get the global event router instance."""
    global _router
    if _router is None:
        _router = EventRouter()
    return _router
