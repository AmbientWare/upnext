"""Conduit API Server."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import get_settings
from server.db.session import get_database, init_database
from server.routes import health_router, v1_router
from server.services import CleanupService, StreamSubscriber, close_redis, connect_redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Conduit API server...")

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
        required_tables = {"job_history", "artifacts", "pending_artifacts"}
        missing_tables = await db.get_missing_tables(required_tables)
        if missing_tables:
            raise RuntimeError(
                "Database schema is missing required tables: "
                + ", ".join(missing_tables)
                + ". Run Alembic migrations (e.g. `alembic upgrade head`) before starting."
            )

    # Connect to Redis and start stream subscribers
    subscriber = None
    redis_client = None

    if settings.redis_url:
        redis_client = await connect_redis(settings.redis_url)
        logger.info("Redis connected")

        subscriber = StreamSubscriber(redis_client=redis_client)
        await subscriber.start()
    else:
        logger.info("Redis not configured (CONDUIT_REDIS_URL not set)")

    # Start periodic cleanup service
    cleanup = CleanupService(redis_client=redis_client)
    await cleanup.start()

    yield

    # Shutdown
    logger.info("Shutting down Conduit API server...")

    # Stop background services
    await cleanup.stop()

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
app = FastAPI(
    title="Conduit API",
    description="API server for Conduit job tracking and dashboard",
    version=get_settings().version,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: prod config
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(v1_router)

# Static files directory (built frontend)
STATIC_DIR = Path(__file__).parent.parent.parent / "static"

# Mount static files if the directory exists (production build)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

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
        return {
            "name": "Conduit API",
            "version": get_settings().version,
            "docs": "/docs",
            "note": "Frontend not built. Run 'bun run build' in web/ directory.",
        }


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
