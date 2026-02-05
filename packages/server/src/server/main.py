"""Conduit API Server."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Conduit API",
        "version": "0.1.0",
        "docs": "/docs",
    }


def main():
    """Run the server."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))

    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=os.environ.get("DEBUG", "").lower() == "true",
    )


if __name__ == "__main__":
    main()
