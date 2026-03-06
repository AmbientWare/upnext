"""Authentication routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.auth import require_api_key
from server.config import get_settings
from server.runtime_scope import AuthScope

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthStatusResponse(BaseModel):
    auth_enabled: bool
    runtime_mode: str


class AuthVerifyScopeResponse(BaseModel):
    deployment_id: str
    workspace_id: str | None
    role: str
    mode: str
    subject: str | None


class AuthVerifyUserResponse(BaseModel):
    id: str
    username: str
    is_admin: bool


class AuthVerifyResponse(BaseModel):
    ok: bool
    scope: AuthVerifyScopeResponse
    user: AuthVerifyUserResponse | None


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status() -> AuthStatusResponse:
    """Return whether authentication is enabled (unauthenticated endpoint)."""
    settings = get_settings()
    return AuthStatusResponse(
        auth_enabled=settings.auth_enabled,
        runtime_mode=settings.runtime_mode.value,
    )


@router.post("/verify", response_model=AuthVerifyResponse)
async def auth_verify(
    scope: AuthScope = Depends(require_api_key),
) -> AuthVerifyResponse:
    """Verify that the provided API key is valid."""
    return AuthVerifyResponse(
        ok=True,
        scope=AuthVerifyScopeResponse(
            deployment_id=scope.deployment_id,
            workspace_id=scope.workspace_id,
            role=scope.role.value,
            mode=scope.mode.value,
            subject=scope.subject,
        ),
        user=(
            AuthVerifyUserResponse(
                id=scope.user.id,
                username=scope.user.username,
                is_admin=scope.user.is_admin,
            )
            if scope.user
            else None
        ),
    )
