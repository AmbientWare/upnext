from collections.abc import Mapping
from datetime import datetime

from server.routes._shared import get_stream_json_object

TREND_TRIGGER_EVENTS = frozenset(
    {
        "job.started",
        "job.completed",
        "job.failed",
        "job.retrying",
    }
)


def extract_stream_function_key(data: Mapping[str | bytes, object]) -> str | None:
    parsed = get_stream_json_object(data)
    if not parsed:
        return None
    function = parsed.get("function")
    return str(function) if function else None


def calculate_duration_ms(
    started_at: datetime | None, completed_at: datetime | None
) -> float | None:
    """Calculate job duration in milliseconds."""
    if started_at and completed_at:
        return (completed_at - started_at).total_seconds() * 1000
    return None
