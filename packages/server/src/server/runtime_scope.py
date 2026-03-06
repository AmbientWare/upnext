"""Runtime request scope models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RuntimeModes(StrEnum):
    SELF_HOSTED = "self_hosted"
    CLOUD_RUNTIME = "cloud_runtime"


@dataclass(frozen=True)
class AuthScope:
    """Resolved auth scope for a runtime request."""

    workspace_id: str
    mode: RuntimeModes
    subject: str | None = None
