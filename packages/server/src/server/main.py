"""UpNext API Server."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.config import get_settings
from server.db.repositories import AuthRepository
from server.db.session import get_database, init_database
from server.logging import configure_logging
from server.middleware import CorrelationIDMiddleware
from server.routes import health_router, v1_admin_router, v1_public_router, v1_router
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

    # Initialize database (defaults to SQLite if not configured)
    db = init_database(settings.effective_database_url)
    await db.connect()

    if settings.is_sqlite:
        logger.info("Database connected (SQLite)")
        # Auto-create tables for SQLite
        await db.create_tables()
    else:
        logger.info("Database connected (PostgreSQL)")
        required_tables = {"job_history", "artifacts", "pending_artifacts", "users", "api_keys"}
        missing_tables = await db.get_missing_tables(required_tables)
        if missing_tables:
            raise RuntimeError(
                "Database schema is missing required tables: "
                + ", ".join(missing_tables)
                + ". Run Alembic migrations (e.g. `alembic upgrade head`) before starting."
            )

    # Seed admin user + API key when auth is enabled
    if settings.auth_enabled:
        logger.info("Authentication enabled")
        if settings.api_key:
            async with db.session() as session:
                await AuthRepository(session).seed_admin_api_key(settings.api_key)
        else:
            logger.warning(
                "UPNEXT_AUTH_ENABLED=true but no UPNEXT_API_KEY set. "
                "No seed key created — all /api/v1 requests will require a valid key."
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
                batch_size=settings.event_subscriber_batch_size,
                poll_interval=settings.event_subscriber_poll_interval_ms / 1000,
                stale_claim_ms=settings.event_subscriber_stale_claim_ms,
                invalid_events_stream=settings.event_subscriber_invalid_stream,
                invalid_events_stream_maxlen=settings.event_subscriber_invalid_stream_maxlen,
            ),
        )
        await subscriber.start()
        register_subscriber(subscriber)
    else:
        logger.info("Redis not configured (UPNEXT_REDIS_URL not set)")

    # Start periodic cleanup service
    cleanup = CleanupService(
        redis_client=redis_client,
        retention_days=settings.cleanup_retention_days,
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

    # Disconnect database
    db = get_database()
    await db.disconnect()
    logger.info("Database disconnected")


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
app.include_router(v1_admin_router)

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
