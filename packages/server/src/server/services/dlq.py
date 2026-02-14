"""Dead-letter queue service — reads DLQ entries from Redis streams."""

import json
import logging

from shared.keys import function_dlq_stream_key, function_dlq_stream_pattern

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _parse_dlq_entry(
    function: str, msg_id: object, msg_data: dict[str | bytes, object]
) -> dict[str, object]:
    """Parse a single DLQ stream entry into a response dict."""
    entry_id = _decode_text(msg_id)
    job_id = _decode_text(msg_data.get("job_id", ""))
    failed_at = _decode_text(msg_data.get("failed_at", "")) or None
    reason = _decode_text(msg_data.get("reason", "")) or None
    attempts = 0
    max_retries = 0
    kwargs: dict[str, object] = {}

    data_raw = msg_data.get("data")
    if data_raw:
        try:
            job_data = json.loads(_decode_text(data_raw))
            job_id = job_id or job_data.get("id", "")
            attempts = int(job_data.get("attempt", 0))
            max_retries = int(job_data.get("max_retries", 0))
            kwargs = job_data.get("kwargs", {})
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    attempts_raw = msg_data.get("attempts")
    if attempts_raw:
        try:
            attempts = int(_decode_text(attempts_raw))
        except ValueError:
            pass

    max_retries_raw = msg_data.get("max_retries")
    if max_retries_raw:
        try:
            max_retries = int(_decode_text(max_retries_raw))
        except ValueError:
            pass

    return {
        "entry_id": entry_id,
        "function": function,
        "job_id": job_id,
        "failed_at": failed_at,
        "reason": reason,
        "attempts": attempts,
        "max_retries": max_retries,
        "kwargs": kwargs,
    }


async def get_dead_letter_entry(function: str, entry_id: str) -> dict[str, object] | None:
    """Fetch a single dead-letter entry by stream ID."""
    r = await get_redis()
    dlq_key = function_dlq_stream_key(function)
    rows: list[tuple[object, dict[str | bytes, object]]] = await r.xrange(
        dlq_key, min=entry_id, max=entry_id, count=1
    )
    if not rows:
        return None
    msg_id, msg_data = rows[0]
    return _parse_dlq_entry(function, msg_id, msg_data)


async def list_dead_letters(
    function: str,
    *,
    limit: int = 100,
) -> list[dict[str, object]]:
    """List dead-letter entries for a function from its DLQ Redis stream."""
    r = await get_redis()
    dlq_key = function_dlq_stream_key(function)

    rows: list[tuple[object, dict[str | bytes, object]]] = await r.xrevrange(
        dlq_key, count=max(1, limit)
    )

    return [_parse_dlq_entry(function, msg_id, msg_data) for msg_id, msg_data in rows]


async def get_dlq_count(function: str) -> int:
    """Get count of entries in a function's DLQ stream."""
    r = await get_redis()
    dlq_key = function_dlq_stream_key(function)
    return int(await r.xlen(dlq_key))


async def delete_dead_letter(function: str, entry_id: str) -> bool:
    """Delete a single dead-letter entry by stream ID."""
    r = await get_redis()
    dlq_key = function_dlq_stream_key(function)
    deleted: int = await r.xdel(dlq_key, entry_id)
    return deleted > 0


async def purge_dead_letters(function: str) -> int:
    """Purge all dead-letter entries for a function. Returns count deleted."""
    r = await get_redis()
    dlq_key = function_dlq_stream_key(function)
    count: int = await r.xlen(dlq_key)
    if count > 0:
        await r.delete(dlq_key)
    return count


async def get_dlq_summary() -> tuple[int, int]:
    """Get total DLQ entries and affected function count across all functions.

    Returns:
        (total_entries, functions_affected)
    """
    r = await get_redis()
    pattern = function_dlq_stream_pattern()
    total_entries = 0
    functions_affected = 0

    async for dlq_key in r.scan_iter(match=pattern, count=100):
        count: int = await r.xlen(dlq_key)
        if count > 0:
            total_entries += count
            functions_affected += 1

    return total_entries, functions_affected


async def list_dlq_functions() -> list[str]:
    """Scan Redis for all functions that have DLQ streams."""
    r = await get_redis()
    pattern = function_dlq_stream_pattern()
    functions: list[str] = []

    async for dlq_key in r.scan_iter(match=pattern, count=100):
        key_str = _decode_text(dlq_key)
        # Key format: upnext:fn:{function}:dlq
        parts = key_str.split(":")
        try:
            fn_idx = parts.index("fn")
            fn_name = parts[fn_idx + 1]
            if fn_name and fn_name != "*":
                functions.append(fn_name)
        except (ValueError, IndexError):
            continue

    return sorted(functions)
