"""Authentication dependencies for UpNext API."""

import logging
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request

from server.config import get_settings
from server.db.repositories import AuthRepository, hash_api_key
from server.db.session import Database, get_database
from server.db.tables import User

logger = logging.getLogger(__name__)


async def require_api_key(
    request: Request,
    db: Database = Depends(lambda: get_database()),
) -> User | None:
    """FastAPI dependency that enforces API key auth when enabled.

    When ``UPNEXT_AUTH_ENABLED`` is False the dependency is a no-op and
    returns None so routes work without authentication.

    When enabled, expects an ``Authorization: Bearer <key>`` header.
    Returns the associated ``User`` on success, raises 401/403 otherwise.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return None

    # Accept key from Authorization header or ?token= query param (for SSE/EventSource)
    raw_key: str | None = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        raw_key = auth_header.removeprefix("Bearer ").strip()
    if not raw_key:
        raw_key = request.query_params.get("token")
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    key_hash = hash_api_key(raw_key)

    async with db.session() as session:
        repo = AuthRepository(session)
        api_key = await repo.get_api_key_by_hash(key_hash)

        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        if not api_key.is_active:
            raise HTTPException(status_code=403, detail="API key is disabled")

        # Update last_used_at
        api_key.last_used_at = datetime.now(UTC)

        user = await repo.get_user_by_id(api_key.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

    return user
