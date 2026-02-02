"""Health check routes."""

from fastapi import APIRouter
from shared.events import HealthResponse

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
        version="0.1.0",
        tier="free",
        features=[],
    )
