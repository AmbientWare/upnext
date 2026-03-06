"""Minimal authentication routes"""

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
    mode: str
    subject: str | None


class AuthVerifyResponse(BaseModel):
    ok: bool
    scope: AuthVerifyScopeResponse


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status() -> AuthStatusResponse:
    settings = get_settings()
    return AuthStatusResponse(
        auth_enabled=settings.is_cloud_runtime or settings.auth_enabled,
        runtime_mode=settings.runtime_mode.value,
    )


@router.post("/verify", response_model=AuthVerifyResponse)
async def auth_verify(
    scope: AuthScope = Depends(require_api_key),
) -> AuthVerifyResponse:
    return AuthVerifyResponse(
        ok=True,
        scope=AuthVerifyScopeResponse(
            deployment_id=scope.deployment_id,
            workspace_id=scope.workspace_id,
            mode=scope.mode.value,
            subject=scope.subject,
        ),
    )
