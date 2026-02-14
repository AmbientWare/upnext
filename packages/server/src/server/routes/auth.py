"""Authentication routes."""

from fastapi import APIRouter, Depends

from server.auth import require_api_key
from server.config import get_settings
from server.db.tables import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
async def auth_status():
    """Return whether authentication is enabled (unauthenticated endpoint)."""
    settings = get_settings()
    return {"auth_enabled": settings.auth_enabled}


@router.post("/verify", dependencies=[Depends(require_api_key)])
async def auth_verify():
    """Verify that the provided API key is valid.

    Returns 200 if valid, 401/403 if not (handled by the dependency).
    """
    return {"ok": True}
