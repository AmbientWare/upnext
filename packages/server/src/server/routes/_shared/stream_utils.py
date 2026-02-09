"""Shared helpers for reading Redis stream payload fields."""

import json
from collections.abc import Mapping
from typing import Any, TypeAlias

StreamEntry: TypeAlias = Mapping[str | bytes, object]


def get_stream_text_field(data: StreamEntry, key: str) -> str | None:
    """Decode a field from a stream entry supporting str/bytes keys."""
    raw: Any = data.get(key)
    if raw is None:
        raw = data.get(key.encode())
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


def get_stream_json_object(
    data: StreamEntry, key: str = "data"
) -> dict[str, Any] | None:
    """Parse a JSON object from a decoded stream field."""
    payload = get_stream_text_field(data, key)
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
