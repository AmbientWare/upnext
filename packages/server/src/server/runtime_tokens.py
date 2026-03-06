"""Minimal HS256 runtime token helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any


class RuntimeTokenError(ValueError):
    """Raised when a runtime token is invalid."""


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_runtime_token(
    token: str,
    *,
    secret: str,
    expected_issuer: str,
    expected_audience: str,
) -> dict[str, Any]:
    """Decode and validate a compact HS256 JWT."""

    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise RuntimeTokenError("Malformed runtime token") from exc

    signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature_segment, _b64url_encode(expected_signature)):
        raise RuntimeTokenError("Invalid runtime token signature")

    try:
        header = json.loads(_b64url_decode(header_segment))
        payload = json.loads(_b64url_decode(payload_segment))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeTokenError("Invalid runtime token payload") from exc

    if header.get("alg") != "HS256":
        raise RuntimeTokenError("Unsupported runtime token algorithm")

    if payload.get("iss") != expected_issuer:
        raise RuntimeTokenError("Invalid runtime token issuer")
    if payload.get("aud") != expected_audience:
        raise RuntimeTokenError("Invalid runtime token audience")

    exp = payload.get("exp")
    if not isinstance(exp, int | float):
        raise RuntimeTokenError("Runtime token is missing exp")
    now = datetime.now(UTC).timestamp()
    if exp <= now:
        raise RuntimeTokenError("Runtime token has expired")

    return payload
