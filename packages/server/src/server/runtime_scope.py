"""Runtime request scope models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from server.backends.base.models import User


class RuntimeModes(StrEnum):
    SELF_HOSTED = "self_hosted"
    CLOUD_RUNTIME = "cloud_runtime"


class RuntimeRoles(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


@dataclass(frozen=True)
class AuthScope:
    """Resolved auth scope for a runtime request."""

    deployment_id: str
    workspace_id: str | None
    role: RuntimeRoles
    mode: RuntimeModes
    subject: str | None = None
    user: User | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == RuntimeRoles.ADMIN
