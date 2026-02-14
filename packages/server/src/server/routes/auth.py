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


@router.post("/verify")
async def auth_verify(user: User | None = Depends(require_api_key)):
    """Verify that the provided API key is valid.

    Returns 200 with user info if valid, 401/403 if not (handled by the dependency).
    """
    return {
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "is_admin": user.is_admin,
        }
        if user
        else None,
    }
