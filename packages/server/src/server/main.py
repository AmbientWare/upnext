"""Conduit API Server."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from server.db.session import init_database
from server.routes import (
    dashboard_router,
    endpoints_router,
    events_router,
    functions_router,
    health_router,
    jobs_router,
    workers_router,
)

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

    # Initialize database if configured
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        db = init_database(database_url)
        await db.connect()
        logger.info("Database connected")
    else:
        logger.warning("DATABASE_URL not set, running without persistence")

    yield

    # Shutdown
    logger.info("Shutting down Conduit API server...")
    if database_url:
        from server.db.session import get_database

        db = get_database()
        await db.disconnect()
        logger.info("Database disconnected")


# Create FastAPI app
app = FastAPI(
    title="Conduit API",
    description="API server for Conduit job tracking and dashboard",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(events_router, prefix="/api/v1")
app.include_router(workers_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(functions_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(endpoints_router, prefix="/api/v1")


# Static files directory (built frontend)
STATIC_DIR = Path(__file__).parent.parent.parent / "static"

# Mount static files if the directory exists (production build)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA for all non-API routes."""
        # Try to serve the requested file
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # Fall back to index.html for SPA routing
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/")
    async def root():
        """Root endpoint (dev mode without built frontend)."""
        return {
            "name": "Conduit API",
            "version": "0.1.0",
            "docs": "/docs",
            "note": "Frontend not built. Run 'bun run build' in web/ directory.",
        }


def main():
    """Run the server."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))

    uvicorn.run(
        "server.main:app",
        host=host,
        port=port,
        reload=os.environ.get("DEBUG", "").lower() == "true",
    )


if __name__ == "__main__":
    main()
