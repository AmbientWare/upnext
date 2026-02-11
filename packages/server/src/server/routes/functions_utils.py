"""Utility helpers for function routes."""

from __future__ import annotations

import json
from typing import Any

from shared.schemas import FunctionConfig
from shared.workers import FUNCTION_KEY_PREFIX

from server.services.redis import get_redis


async def set_function_pause_state(
    function_key: str, *, paused: bool
) -> dict[str, Any] | None:
    """
    Persist pause state for a function definition.

    Returns:
        Dict payload if function exists, else None.
    """
    redis_client = await get_redis()
    redis_key = f"{FUNCTION_KEY_PREFIX}:{function_key}"
    raw = await redis_client.get(redis_key)
    if not raw:
        return None

    payload = raw.decode() if isinstance(raw, bytes) else str(raw)
    try:
        config = FunctionConfig.model_validate_json(payload)
    except Exception:
        raise ValueError(f"Invalid function definition for '{function_key}'")

    updated = config.model_dump()
    updated["paused"] = paused

    ttl = await redis_client.ttl(redis_key)
    encoded = json.dumps(updated)
    if ttl == -2:
        return None
    if ttl == -1:
        await redis_client.set(redis_key, encoded)
    else:
        # Preserve expiring keys even when TTL rounds down to zero.
        await redis_client.setex(redis_key, max(1, int(ttl)), encoded)

    return {
        "key": function_key,
        "paused": paused,
    }
