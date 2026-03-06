"""UpNext API Server."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from shared.keys import DEFAULT_WORKSPACE_ID

from server.backends import get_backend
from server.backends.types import PersistenceBackends
from server.config import get_settings
from server.logging import configure_logging
from server.middleware import CorrelationIDMiddleware
from server.routes import health_router, v1_public_router, v1_router
from server.services.events import (
    StreamSubscriber,
    StreamSubscriberConfig,
    register_subscriber,
)
from server.services.operations import (
    AlertEmitterService,
    CleanupService,
)
from server.services.redis import (
    close_redis,
    connect_redis,
)

# Configure logging (supports UPNEXT_LOG_FORMAT=json for structured output).
_boot_settings = get_settings()
configure_logging(log_format=_boot_settings.log_format, debug=_boot_settings.debug)
logger = logging.getLogger(__name__)

_REQUIRED_SQL_TABLES = {
    "job_history",
    "artifacts",
    "pending_artifacts",
    "secrets",
}


class AppResponse(BaseModel):
    """App response."""

    name: str = "UpNext API"
    version: str = get_settings().version
    docs: str = "/docs"
    note: str = "Frontend not built. Run 'bun run build' in web/ directory."


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan handler."""

    # Startup
    logger.info("Starting UpNext API server...")

    settings = get_settings()
    backend = get_backend(initialized=False)
    await backend.connect()
    await backend.prepare_startup(_REQUIRED_SQL_TABLES)
    logger.info("Persistence connected (%s)", backend.backend_name)

    if settings.is_cloud_runtime:
        logger.info("Cloud runtime mode enabled")
        if settings.backend != PersistenceBackends.POSTGRES:
            raise RuntimeError(
                "Cloud runtime requires UPNEXT_BACKEND=postgres for scoped persistence"
            )
        if settings.normalized_workspace_id == DEFAULT_WORKSPACE_ID:
            raise RuntimeError(
                "Cloud runtime requires UPNEXT_WORKSPACE_ID to be set to a non-local value"
            )
        if not settings.runtime_token_secret:
            logger.warning(
                "UPNEXT_RUNTIME_MODE=cloud_runtime but no runtime token secret is set. "
                "Protected routes will reject all requests until "
                "UPNEXT_RUNTIME_TOKEN_SECRET is configured."
            )
    elif settings.auth_enabled:
        logger.info("Self-hosted authentication enabled")
        if not settings.api_key:
            raise RuntimeError(
                "UPNEXT_AUTH_ENABLED=true requires UPNEXT_API_KEY to be configured"
            )
    else:
        logger.info("Authentication disabled (set UPNEXT_AUTH_ENABLED=true to enable)")

    # Connect to Redis and start stream subscribers
    subscriber = None
    redis_client = None

    if settings.redis_url:
        redis_client = await connect_redis(settings.redis_url)
        logger.info("Redis connected")

        subscriber = StreamSubscriber(
            redis_client=redis_client,
            config=StreamSubscriberConfig(
                stream=settings.status_events_stream,
                batch_size=settings.event_subscriber_batch_size,
                poll_interval=settings.event_subscriber_poll_interval_ms / 1000,
                stale_claim_ms=settings.event_subscriber_stale_claim_ms,
                invalid_events_stream=settings.effective_invalid_events_stream,
                invalid_events_stream_maxlen=settings.event_subscriber_invalid_stream_maxlen,
            ),
        )
        await subscriber.start()
        register_subscriber(subscriber)
    else:
        logger.info("Redis not configured (UPNEXT_REDIS_URL not set)")

    cleanup_retention_hours = settings.cleanup_retention_hours
    if cleanup_retention_hours is None:
        raise RuntimeError(
            "cleanup_retention_hours was not initialized. This should never happen."
        )

    # Start periodic cleanup service
    cleanup = CleanupService(
        redis_client=redis_client,
        retention_hours=cleanup_retention_hours,
        interval_hours=settings.cleanup_interval_hours,
        pending_retention_hours=settings.cleanup_pending_retention_hours,
        pending_promote_batch=settings.cleanup_pending_promote_batch,
        pending_promote_max_loops=settings.cleanup_pending_promote_max_loops,
        startup_jitter_seconds=settings.cleanup_startup_jitter_seconds,
    )
    await cleanup.start()

    alert_emitter = AlertEmitterService(
        interval_seconds=settings.alert_poll_interval_seconds
    )
    await alert_emitter.start()

    yield

    # Shutdown
    logger.info("Shutting down UpNext API server...")

    # Stop background services
    await cleanup.stop()
    await alert_emitter.stop()

    if subscriber:
        await subscriber.stop()

    # Close Redis
    if redis_client:
        await close_redis()
        logger.info("Redis disconnected")

    # Disconnect persistence backend
    await backend.disconnect()
    logger.info("Persistence disconnected")


# Create FastAPI app
app_settings = get_settings()
app = FastAPI(
    title="UpNext API",
    description="API server for UpNext job tracking and dashboard",
    version=app_settings.version,
    lifespan=lifespan,
)

# Add correlation ID middleware (runs before CORS so the ID is on every response)
app.add_middleware(CorrelationIDMiddleware)

# Add CORS middleware
allow_origins = app_settings.cors_allow_origins_list
allow_credentials = app_settings.cors_allow_credentials and "*" not in allow_origins
if app_settings.cors_allow_credentials and "*" in allow_origins:
    logger.warning(
        "CORS credentials disabled because wildcard origins are configured. "
        "Set UPNEXT_CORS_ALLOW_ORIGINS to explicit origins to enable credentials."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(v1_public_router)
app.include_router(v1_router)

# Static files directory (built frontend)
# Prefer packaged assets (`server/static`) and fall back to monorepo path.
PACKAGE_STATIC_DIR = Path(__file__).resolve().parent / "static"
SOURCE_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
STATIC_DIR = PACKAGE_STATIC_DIR if PACKAGE_STATIC_DIR.exists() else SOURCE_STATIC_DIR

# Mount static files if the directory exists (production build)
if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes."""
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")

else:

    @app.get("/")
    async def root():
        """Root endpoint (dev mode without built frontend)."""
        return AppResponse()


def main():
    """Run the server."""
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "server.main:app",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
