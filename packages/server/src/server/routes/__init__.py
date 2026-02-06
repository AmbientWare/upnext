"""API routes."""

from fastapi import APIRouter

from server.routes.apis import router as apis_router
from server.routes.artifacts import router as artifacts_router
from server.routes.dashboard import router as dashboard_router
from server.routes.events import router as events_router
from server.routes.functions import router as functions_router
from server.routes.health import router as health_router
from server.routes.jobs import router as jobs_router
from server.routes.workers import router as workers_router

v1_router = APIRouter(prefix="/api/v1")

# Include routers
v1_router.include_router(artifacts_router)
v1_router.include_router(events_router)
v1_router.include_router(workers_router)
v1_router.include_router(jobs_router)
v1_router.include_router(functions_router)
v1_router.include_router(dashboard_router)
v1_router.include_router(apis_router)

__all__ = [
    "v1_router",
    "health_router",
]
