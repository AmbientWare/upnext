"""API routes."""

from fastapi import APIRouter, Depends

from server.auth import require_api_key
from server.routes.admin import router as admin_router
from server.routes.apis import router as apis_router
from server.routes.artifacts import router as artifacts_router
from server.routes.auth import router as auth_router
from server.routes.dashboard import router as dashboard_router
from server.routes.dlq import router as dlq_router
from server.routes.events_stream import router as events_stream_router
from server.routes.functions import router as functions_router
from server.routes.health import router as health_router
from server.routes.jobs import router as jobs_router
from server.routes.metrics import router as metrics_router
from server.routes.secrets import router as secrets_router
from server.routes.workers import router as workers_router

# Public routes (no auth required)
v1_public_router = APIRouter(prefix="/api/v1")
v1_public_router.include_router(auth_router)

# Protected routes (auth required when enabled)
v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

# Include routers
v1_router.include_router(events_stream_router)
v1_router.include_router(workers_router)
v1_router.include_router(jobs_router)
v1_router.include_router(artifacts_router)
v1_router.include_router(functions_router)
v1_router.include_router(dlq_router)
v1_router.include_router(dashboard_router)
v1_router.include_router(metrics_router)
v1_router.include_router(apis_router)
v1_router.include_router(secrets_router)
v1_router.include_router(admin_router)

__all__ = [
    "v1_public_router",
    "v1_router",
    "health_router",
]
