"""Shared FastAPI dependencies for route handlers."""

from fastapi import HTTPException

from server.db.session import Database, get_database


def require_database() -> Database:
    """FastAPI dependency that returns the database or raises 503."""
    try:
        return get_database()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")
