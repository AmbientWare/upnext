from __future__ import annotations


def normalize_idempotency_key(raw_key: str) -> str:
    """Validate and normalize an idempotency key."""
    key = raw_key.strip()
    if not key:
        raise ValueError("idempotency_key must be a non-empty string")
    if len(key) > 256:
        raise ValueError("idempotency_key must be 256 characters or fewer")
    return key
