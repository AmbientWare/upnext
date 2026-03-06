"""Authentication dependencies for UpNext API."""

import logging
from secrets import compare_digest

from fastapi import Depends, HTTPException, Request

from server.config import get_settings
from server.runtime_scope import AuthScope, RuntimeModes, RuntimeRoles
from server.runtime_tokens import RuntimeTokenError, decode_runtime_token

logger = logging.getLogger(__name__)


def _cache_scope(request: Request, scope: AuthScope) -> AuthScope:
    request.state.auth_scope = scope
    return scope


def _self_hosted_scope(
    *,
    subject: str | None,
) -> AuthScope:
    settings = get_settings()
    return AuthScope(
        deployment_id=settings.normalized_default_deployment_id,
        workspace_id=None,
        role=RuntimeRoles.ADMIN,
        mode=RuntimeModes.SELF_HOSTED,
        subject=subject,
    )


def get_request_scope(request: Request | None = None) -> AuthScope:
    """Return the resolved request scope or a local self-hosted fallback."""

    if request is not None:
        cached = getattr(request.state, "auth_scope", None)
        if isinstance(cached, AuthScope):
            return cached

    return _self_hosted_scope(subject="local-admin")


async def require_api_key(
    request: Request,
) -> AuthScope:
    """FastAPI dependency that enforces API key auth when enabled.

    When ``UPNEXT_AUTH_ENABLED`` is False the dependency is a no-op and
    returns a local admin scope so routes work without authentication.

    When enabled, expects an ``Authorization: Bearer <key>`` header.

    The database is only accessed when auth is enabled, avoiding crashes
    in environments where the DB hasn't been initialised yet.
    """
    settings = get_settings()
    if settings.is_cloud_runtime:
        if not settings.runtime_token_secret:
            raise HTTPException(
                status_code=500,
                detail="Cloud runtime token secret is not configured",
            )

        runtime_token: str | None = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            runtime_token = auth_header.removeprefix("Bearer ").strip()
        if not runtime_token:
            raise HTTPException(
                status_code=401, detail="Missing or invalid Authorization header"
            )

        try:
            claims = decode_runtime_token(
                runtime_token,
                secret=settings.runtime_token_secret,
                expected_issuer=settings.runtime_token_issuer,
                expected_audience=settings.runtime_token_audience,
            )
        except RuntimeTokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        deployment_id = claims.get("deployment_id")
        workspace_id = claims.get("workspace_id")
        role = claims.get("role")
        subject = claims.get("sub")

        if not isinstance(deployment_id, str) or not deployment_id:
            raise HTTPException(
                status_code=401, detail="Runtime token missing deployment_id"
            )
        if deployment_id != settings.normalized_default_deployment_id:
            raise HTTPException(
                status_code=403,
                detail="Runtime token deployment_id does not match this runtime",
            )
        if workspace_id is not None and not isinstance(workspace_id, str):
            raise HTTPException(
                status_code=401, detail="Runtime token has invalid workspace_id"
            )
        if role not in {"viewer", "operator", "admin"}:
            raise HTTPException(
                status_code=401, detail="Runtime token has invalid role"
            )
        if subject is not None and not isinstance(subject, str):
            raise HTTPException(
                status_code=401, detail="Runtime token has invalid subject"
            )

        return _cache_scope(
            request,
            AuthScope(
                deployment_id=deployment_id,
                workspace_id=workspace_id,
                role=RuntimeRoles(role),
                mode=RuntimeModes.CLOUD_RUNTIME,
                subject=subject,
            ),
        )

    if not settings.auth_enabled:
        return _cache_scope(request, _self_hosted_scope(subject="local-admin"))

    raw_token: str | None = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header.removeprefix("Bearer ").strip()

    if not raw_token:
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    configured_token = settings.api_key
    if not configured_token:
        raise HTTPException(
            status_code=500,
            detail="Self-hosted authentication is enabled but no API key is configured",
        )
    if not compare_digest(raw_token, configured_token):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return _cache_scope(request, _self_hosted_scope(subject="self-hosted-token"))


async def require_auth_scope(
    request: Request,
    scope: AuthScope = Depends(require_api_key),
) -> AuthScope:
    """Typed auth dependency for protected routes."""
    return _cache_scope(request, scope)


async def require_admin(
    scope: AuthScope = Depends(require_api_key),
) -> AuthScope:
    """FastAPI dependency that enforces admin access.

    Chains through ``require_api_key`` internally so routers only need
    ``dependencies=[Depends(require_admin)]``.
    """
    if not scope.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    return scope
