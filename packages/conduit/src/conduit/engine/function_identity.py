"""Deterministic function identity helpers.

Conduit uses stable function keys for internal routing/queue identity while
keeping human-readable names for UI and logs.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

FunctionKind = Literal["task", "cron", "event"]

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    normalized = _NON_ALNUM_RE.sub("_", lowered).strip("_")
    return normalized or "fn"


def build_function_key(
    kind: FunctionKind,
    *,
    module: str,
    qualname: str,
    name: str,
    schedule: str | None = None,
    pattern: str | None = None,
) -> str:
    """Build a stable function key safe for Redis key segments and URLs."""
    basis = "|".join(
        [
            kind,
            module,
            qualname,
            name,
            schedule or "",
            pattern or "",
        ]
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"{kind}_{_slug(name)}_{digest}"
