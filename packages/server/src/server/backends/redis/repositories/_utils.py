"""Utility helpers for Redis-backed persistence repositories."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def encode_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def decode_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def dumps(data: Mapping[str, object]) -> str:
    return json.dumps(data, default=str)


def loads(raw: object) -> dict[str, object] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    return value
