"""Helpers for reading API request events from Redis streams."""

from collections.abc import AsyncGenerator, Mapping
from datetime import UTC, datetime
from typing import Any

from shared.keys import API_REQUESTS_STREAM


def stream_id_floor(value: datetime) -> str:
    """Build inclusive Redis stream id for datetime lower-bound filtering."""
    ts_ms = int(value.astimezone(UTC).timestamp() * 1000)
    return f"{ts_ms}-0"


def stream_id_ceil(value: datetime) -> str:
    """Build inclusive Redis stream id for datetime upper-bound filtering."""
    ts_ms = int(value.astimezone(UTC).timestamp() * 1000)
    return f"{ts_ms}-999999"


async def _xrevrange_compat(
    redis_client: Any,
    *,
    max_id: str,
    min_id: str,
    count: int,
) -> list[tuple[object, Mapping[str | bytes, object]]]:
    """
    Read stream rows with compatibility for lightweight test stubs.

    Production redis client supports `xrevrange(name, max=..., min=..., count=...)`.
    Some tests monkeypatch stubs with the old `(stream, count)` signature.
    """
    try:
        rows = await redis_client.xrevrange(
            API_REQUESTS_STREAM,
            max=max_id,
            min=min_id,
            count=count,
        )
    except TypeError:
        rows = await redis_client.xrevrange(API_REQUESTS_STREAM, count=count)
    return rows


async def iter_api_request_rows(
    redis_client: Any,
    *,
    max_id: str,
    min_id: str,
    count: int,
) -> AsyncGenerator[tuple[str, Mapping[str | bytes, object]], None]:
    """Iterate stream rows in reverse chronological order using paged xrevrange."""
    cursor = max_id
    while True:
        rows = await _xrevrange_compat(
            redis_client,
            max_id=cursor,
            min_id=min_id,
            count=count,
        )
        if not rows:
            break

        for event_id, row in rows:
            if isinstance(event_id, bytes):
                event_id_str = event_id.decode()
            else:
                event_id_str = str(event_id)
            yield event_id_str, row

        if len(rows) < count:
            break

        last_event_id = rows[-1][0]
        if isinstance(last_event_id, bytes):
            last_event_id_str = last_event_id.decode()
        else:
            last_event_id_str = str(last_event_id)
        cursor = f"({last_event_id_str}"
