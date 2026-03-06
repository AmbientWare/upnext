"""Shared helper functions used across persistence backends."""

from __future__ import annotations

import json
import mimetypes


def infer_artifact_metadata(
    *,
    data: object | None,
    path: str | None,
    size_bytes: int | None,
    content_type: str | None,
) -> tuple[int | None, str | None]:
    """Derive missing artifact metadata for backwards compatibility."""
    resolved_size = size_bytes
    resolved_type = content_type

    if resolved_size is None and data is not None:
        if isinstance(data, (bytes, bytearray)):
            resolved_size = len(data)
        elif isinstance(data, str):
            resolved_size = len(data.encode())
        else:
            try:
                resolved_size = len(json.dumps(data, default=str).encode())
            except Exception:
                resolved_size = len(str(data).encode())

    if resolved_type is None and path:
        guessed, _encoding = mimetypes.guess_type(path)
        resolved_type = guessed

    if resolved_type is None and data is not None:
        if isinstance(data, (dict, list)):
            resolved_type = "application/json"
        elif isinstance(data, str):
            resolved_type = "text/plain"
        elif isinstance(data, (bytes, bytearray)):
            resolved_type = "application/octet-stream"

    return resolved_size, resolved_type
