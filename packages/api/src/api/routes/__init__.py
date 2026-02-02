"""API routes."""

from api.routes.dashboard import router as dashboard_router
from api.routes.endpoints import router as endpoints_router
from api.routes.events import router as events_router
from api.routes.functions import router as functions_router
from api.routes.health import router as health_router
from api.routes.jobs import router as jobs_router
from api.routes.workers import router as workers_router

__all__ = [
    "dashboard_router",
    "endpoints_router",
    "events_router",
    "functions_router",
    "health_router",
    "jobs_router",
    "workers_router",
]
