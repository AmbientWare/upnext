"""Authentication dependencies for UpNext API."""

import logging
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request

from server.backends import get_backend
from server.backends.base.models import User
from server.backends.base.utils import hash_api_key
from server.config import get_settings

logger = logging.getLogger(__name__)


async def require_api_key(
    request: Request,
) -> User | None:
    """FastAPI dependency that enforces API key auth when enabled.

    When ``UPNEXT_AUTH_ENABLED`` is False the dependency is a no-op and
    returns None so routes work without authentication.

    When enabled, expects an ``Authorization: Bearer <key>`` header.

    The database is only accessed when auth is enabled, avoiding crashes
    in environments where the DB hasn't been initialised yet.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return None

    # Extract key from Authorization header
    raw_key: str | None = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        raw_key = auth_header.removeprefix("Bearer ").strip()

    if not raw_key:
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    key_hash = hash_api_key(raw_key)

    backend = get_backend()
    async with backend.session() as tx:
        api_key = await tx.auth.get_api_key_by_hash(key_hash)

        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        if not api_key.is_active:
            raise HTTPException(status_code=403, detail="API key is disabled")

        now = datetime.now(UTC)
        api_key.last_used_at = now
        api_key.updated_at = now
        await tx.auth.save_api_key(api_key)

        user = await tx.auth.get_user_by_id(api_key.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

    return user


async def require_admin(
    user: User | None = Depends(require_api_key),
) -> User | None:
    """FastAPI dependency that enforces admin access.

    Chains through ``require_api_key`` internally so routers only need
    ``dependencies=[Depends(require_admin)]``.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return None

    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    return user
