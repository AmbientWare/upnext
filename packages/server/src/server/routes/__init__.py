"""API routes."""

from server.routes.dashboard import router as dashboard_router
from server.routes.endpoints import router as endpoints_router
from server.routes.events import router as events_router
from server.routes.functions import router as functions_router
from server.routes.health import router as health_router
from server.routes.jobs import router as jobs_router
from server.routes.workers import router as workers_router

__all__ = [
    "dashboard_router",
    "endpoints_router",
    "events_router",
    "functions_router",
    "health_router",
    "jobs_router",
    "workers_router",
]
