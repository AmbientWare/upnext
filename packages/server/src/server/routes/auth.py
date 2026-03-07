"""Authentication routes for self-hosted and cloud runtime access."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from shared.keys import DEFAULT_WORKSPACE_ID, normalize_workspace_id

from server.auth import require_api_key
from server.config import get_settings
from server.runtime_scope import AuthScope
from server.runtime_tokens import RuntimeTokenError, decode_runtime_token, encode_runtime_token

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthStatusResponse(BaseModel):
    auth_enabled: bool
    runtime_mode: str
    default_session_available: bool


class AuthVerifyScopeResponse(BaseModel):
    workspace_id: str
    mode: str
    subject: str | None
    email: str | None
    name: str | None
    picture: str | None


class AuthVerifyResponse(BaseModel):
    ok: bool
    scope: AuthVerifyScopeResponse


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status() -> AuthStatusResponse:
    settings = get_settings()
    return AuthStatusResponse(
        auth_enabled=settings.is_cloud_runtime or settings.auth_enabled,
        runtime_mode=settings.runtime_mode.value,
        default_session_available=(
            settings.is_cloud_runtime and settings.allow_runtime_default_session
        ),
    )


@router.post("/verify", response_model=AuthVerifyResponse)
async def auth_verify(
    scope: AuthScope = Depends(require_api_key),
) -> AuthVerifyResponse:
    return AuthVerifyResponse(
        ok=True,
        scope=AuthVerifyScopeResponse(
            workspace_id=scope.workspace_id,
            mode=scope.mode.value,
            subject=scope.subject,
            email=scope.email,
            name=scope.name,
            picture=scope.picture,
        ),
    )


@router.post("/session/default", response_model=AuthVerifyResponse)
async def create_default_cloud_session(
    response: Response,
    workspace_id: str | None = None,
) -> AuthVerifyResponse:
    settings = get_settings()
    if not settings.is_cloud_runtime:
        raise HTTPException(status_code=404, detail="Not available in self-hosted mode")
    if not settings.runtime_token_secret:
        raise HTTPException(
            status_code=500,
            detail="Cloud runtime token secret is not configured",
        )
    if not settings.allow_runtime_default_session:
        raise HTTPException(
            status_code=403, detail="Default runtime session is disabled"
        )

    normalized_workspace_id = normalize_workspace_id(workspace_id)
    if normalized_workspace_id == DEFAULT_WORKSPACE_ID:
        raise HTTPException(
            status_code=400,
            detail="workspace_id is required for default cloud sessions",
        )

    expires_at = datetime.now(UTC) + timedelta(
        seconds=settings.runtime_session_ttl_seconds
    )
    payload = {
        "iss": settings.runtime_token_issuer,
        "aud": settings.runtime_token_audience,
        "sub": settings.runtime_default_subject,
        "workspace_id": normalized_workspace_id,
        "email": settings.runtime_default_email,
        "name": settings.runtime_default_name,
        "exp": int(expires_at.timestamp()),
    }
    token = encode_runtime_token(payload, secret=settings.runtime_token_secret)
    response.set_cookie(
        key=settings.runtime_session_cookie_name,
        value=token,
        max_age=settings.runtime_session_ttl_seconds,
        httponly=True,
        secure=settings.runtime_session_cookie_secure,
        samesite=settings.runtime_session_cookie_samesite,
        domain=settings.runtime_session_cookie_domain,
        path="/",
    )
    return AuthVerifyResponse(
        ok=True,
        scope=AuthVerifyScopeResponse(
            workspace_id=normalized_workspace_id,
            mode=settings.runtime_mode.value,
            subject=settings.runtime_default_subject,
            email=settings.runtime_default_email,
            name=settings.runtime_default_name,
        ),
    )


@router.get("/session/exchange")
async def exchange_token_for_session(
    token: str = Query(...),
    redirect_uri: str = Query(default="/"),
) -> RedirectResponse:
    """Validate a JWT from the query string, set an HttpOnly cookie, and redirect."""
    settings = get_settings()
    if not settings.is_cloud_runtime:
        raise HTTPException(status_code=404, detail="Not available in self-hosted mode")
    if not settings.runtime_token_secret:
        raise HTTPException(
            status_code=500,
            detail="Cloud runtime token secret is not configured",
        )

    try:
        decode_runtime_token(
            token,
            secret=settings.runtime_token_secret,
            expected_issuer=settings.runtime_token_issuer,
            expected_audience=settings.runtime_token_audience,
        )
    except RuntimeTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    response = RedirectResponse(url=redirect_uri, status_code=302)
    response.set_cookie(
        key=settings.runtime_session_cookie_name,
        value=token,
        max_age=settings.runtime_session_ttl_seconds,
        httponly=True,
        secure=settings.runtime_session_cookie_secure,
        samesite=settings.runtime_session_cookie_samesite,
        domain=settings.runtime_session_cookie_domain,
        path="/",
    )
    return response


@router.post("/session/logout")
async def clear_runtime_session(response: Response) -> dict[str, bool]:
    settings = get_settings()
    response.delete_cookie(
        key=settings.runtime_session_cookie_name,
        domain=settings.runtime_session_cookie_domain,
        path="/",
    )
    return {"ok": True}
