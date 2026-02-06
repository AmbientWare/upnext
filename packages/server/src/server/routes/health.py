"""Health check routes."""

from fastapi import APIRouter
from shared.events import HealthResponse

from server.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns system info.
    Used by workers to validate credentials and get system details.
    """
    return HealthResponse(
        status="ok",
        version=get_settings().version,
        tier="free",
        features=[],
    )
