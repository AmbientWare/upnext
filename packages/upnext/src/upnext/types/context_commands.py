"""Command tuple types exchanged between Context and JobProcessor."""

from typing import Any, Literal, Protocol

type ProgressCommand = tuple[Literal["set_progress"], str, float, str | None]
type CheckpointCommand = tuple[Literal["checkpoint"], str, dict[str, Any]]
type SendLogCommand = tuple[
    Literal["send_log"],
    str,
    str,
    str,
    dict[str, Any],
]
type ContextCommand = ProgressCommand | CheckpointCommand | SendLogCommand
type ContextCommandOrSentinel = ContextCommand | None


class CommandQueueLike(Protocol):
    """Queue protocol for dispatching context commands."""

    def put(
        self,
        item: ContextCommandOrSentinel,
        block: bool = True,
        timeout: float | None = None,
    ) -> None: ...
