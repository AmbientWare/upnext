"""Shared FastAPI dependencies for route handlers."""

from fastapi import HTTPException

from server.backends.service import BackendService, get_backend


def require_backend() -> BackendService:
    """FastAPI dependency that returns backend service or raises 503."""
    try:
        return get_backend()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Backend not available")
