"""
Api class that wraps FastAPI for HTTP endpoints.

This is the user-facing Api that supports @api.get(), @api.post(), etc.
"""

import asyncio
import json
import logging
import signal
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar

import redis.asyncio as aioredis
import uvicorn
from fastapi import APIRouter, FastAPI
from shared.api import API_INSTANCE_PREFIX, API_INSTANCE_TTL

from conduit.config import get_settings
from conduit.sdk.middleware import ApiTrackingMiddleware

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class Api:
    """
    User-facing Api class that wraps FastAPI.

    Example:
        import conduit

        api = conduit.Api("my-api")

        @api.get("/health")
        async def health():
            return {"status": "ok"}

        @api.post("/orders")
        async def create_order(data: dict):
            return {"id": "123", "status": "created"}

        # Run with: conduit dev service.py
    """

    name: str
    host: str = "0.0.0.0"
    port: int = 8000
    docs_url: str = "/docs"
    openapi_url: str = "/openapi.json"
    debug: bool = field(default_factory=lambda: get_settings().debug)

    # Redis URL for API request tracking (auto-detected from CONDUIT_REDIS_URL)
    redis_url: str | None = field(default_factory=lambda: get_settings().redis_url)

    # Signal handling (set to False when signals are handled at a higher level)
    handle_signals: bool = True

    # Internal FastAPI app (created lazily)
    _app: FastAPI | None = field(default=None, init=False)
    _server: Any = field(default=None, init=False)
    _redis: Any = field(default=None, init=False)
    _api_id: str | None = field(default=None, init=False)
    _heartbeat_task: asyncio.Task[None] | None = field(default=None, init=False)
    _started_at: datetime | None = field(default=None, init=False)
    _pending_routers: list[tuple["APIRouter", dict[str, Any]]] = field(
        default_factory=list, init=False
    )

    @property
    def api_id(self) -> str | None:
        """Get the unique instance ID (generated on start)."""
        return self._api_id

    @property
    def app(self) -> FastAPI:
        """Get the underlying FastAPI application."""
        if self._app is None:
            self._app = FastAPI(
                title=self.name,
                docs_url=self.docs_url,
                openapi_url=self.openapi_url,
                debug=self.debug,
            )
        return self._app

    def get(
        self,
        path: str,
        *,
        response_model: Any = None,
        status_code: int = 200,
        tags: list[str | Enum] | None = None,
        summary: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> Callable[[F], F]:
        """
        Decorator for GET endpoints.

        Example:
            @api.get("/users/{user_id}")
            async def get_user(user_id: str):
                return {"id": user_id}
        """
        return self.app.get(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            **kwargs,
        )

    def post(
        self,
        path: str,
        *,
        response_model: Any = None,
        status_code: int = 200,
        tags: list[str | Enum] | None = None,
        summary: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> Callable[[F], F]:
        """
        Decorator for POST endpoints.

        Example:
            @api.post("/users")
            async def create_user(data: UserCreate):
                return {"id": "123", "name": data.name}
        """
        return self.app.post(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            **kwargs,
        )

    def put(
        self,
        path: str,
        *,
        response_model: Any = None,
        status_code: int = 200,
        tags: list[str | Enum] | None = None,
        summary: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> Callable[[F], F]:
        """Decorator for PUT endpoints."""
        return self.app.put(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            **kwargs,
        )

    def patch(
        self,
        path: str,
        *,
        response_model: Any = None,
        status_code: int = 200,
        tags: list[str | Enum] | None = None,
        summary: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> Callable[[F], F]:
        """Decorator for PATCH endpoints."""
        return self.app.patch(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            **kwargs,
        )

    def delete(
        self,
        path: str,
        *,
        response_model: Any = None,
        status_code: int = 200,
        tags: list[str | Enum] | None = None,
        summary: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> Callable[[F], F]:
        """Decorator for DELETE endpoints."""
        return self.app.delete(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            **kwargs,
        )

    def route(
        self,
        path: str,
        methods: list[str] | None = None,
        **kwargs: Any,
    ) -> Callable[[F], F]:
        """
        Decorator for custom HTTP methods.

        Example:
            @api.route("/custom", methods=["GET", "POST"])
            async def custom_handler():
                return {"method": "custom"}
        """
        return self.app.api_route(path, methods=methods, **kwargs)

    def add_middleware(self, middleware_class: type, **options: Any) -> None:
        """
        Add middleware to the API.

        Example:
            from fastapi.middleware.cors import CORSMiddleware

            api.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
            )
        """
        self.app.add_middleware(middleware_class, **options)

    def include_router(self, sub_router: Any, **kwargs: Any) -> None:
        """
        Include a FastAPI router.

        Example:
            from fastapi import APIRouter

            users_router = APIRouter(prefix="/users")

            @users_router.get("/")
            async def list_users():
                return []

            api.include_router(users_router)
        """
        self.app.include_router(sub_router, **kwargs)

    def group(
        self,
        prefix: str,
        *,
        tags: list[str | Enum] | None = None,
        **kwargs: Any,
    ) -> "APIRouter":
        """
        Create a route group with a common prefix (automatically included).

        Example:
            orders = api.group("/orders", tags=["orders"])

            @orders.get("/{order_id}")
            async def get_order(order_id: str):
                return {"id": order_id}

            @orders.post("/")
            async def create_order(data: dict):
                return {"id": "123"}

            # Routes are automatically included:
            # GET /orders/{order_id}
            # POST /orders/
        """
        router = APIRouter(prefix=prefix, tags=tags, **kwargs)
        # Delay inclusion until app starts - routes need to be registered first
        self._pending_routers.append((router, {}))
        return router

    def _include_pending_routers(self) -> None:
        """Include all pending routers in the app (called before start)."""
        for router, kwargs in self._pending_routers:
            self.app.include_router(router, **kwargs)
        self._pending_routers.clear()

    async def _setup_tracking(self) -> None:
        """Set up API request tracking and instance registration via Redis."""
        if not self.redis_url:
            return

        try:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception as e:
            logger.debug(f"Redis not available for API tracking: {e}")
            self._redis = None
            return

        self.app.add_middleware(
            ApiTrackingMiddleware, api_name=self.name, redis_client=self._redis
        )

        # Generate unique instance ID and register in Redis
        self._api_id = f"api_{uuid.uuid4().hex[:8]}"
        self._started_at = datetime.now(UTC)

        await self._write_instance_heartbeat()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.debug(f"API instance registered: {self._api_id}")

    def _get_endpoint_list(self) -> list[str]:
        """Get list of registered endpoint strings (e.g. 'GET:/health')."""
        endpoints: list[str] = []
        for route in self.app.routes:
            if hasattr(route, "methods"):
                path = getattr(route, "path", "")
                for method in getattr(route, "methods", set()):
                    endpoints.append(f"{method}:{path}")
        return endpoints

    def _instance_data(self) -> str:
        """Build JSON instance data for Redis."""
        return json.dumps(
            {
                "id": self._api_id,
                "api_name": self.name,
                "started_at": self._started_at.isoformat() if self._started_at else "",
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "host": self.host,
                "port": self.port,
                "endpoints": self._get_endpoint_list(),
                "hostname": socket.gethostname(),
            }
        )

    async def _write_instance_heartbeat(self) -> None:
        """Write instance data to Redis with TTL."""
        if not self._redis or not self._api_id:
            return
        key = f"{API_INSTANCE_PREFIX}:{self._api_id}"
        await self._redis.setex(key, API_INSTANCE_TTL, self._instance_data())

    async def _heartbeat_loop(self) -> None:
        """Refresh instance TTL in Redis periodically."""
        while True:
            try:
                await asyncio.sleep(10)
                await self._write_instance_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"API heartbeat error: {e}")
                await asyncio.sleep(10)

    async def _cleanup_tracking(self) -> None:
        """Remove instance from Redis and close connection."""
        # Stop heartbeat
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._redis:
            # Remove instance key
            if self._api_id:
                try:
                    await self._redis.delete(f"{API_INSTANCE_PREFIX}:{self._api_id}")
                except Exception:
                    pass

            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None

    async def start(self) -> None:
        """
        Start the API server.

        This runs uvicorn to serve the FastAPI application.
        If handle_signals is True (default), SIGINT/SIGTERM will trigger graceful shutdown.
        """

        # Include any pending routers before starting
        self._include_pending_routers()

        # Set up request tracking
        await self._setup_tracking()

        logger.debug(f"Starting API '{self.name}' on {self.host}:{self.port}")

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",  # Quiet uvicorn logs
            timeout_graceful_shutdown=1,  # Must be < TASK_WAIT_TIMEOUT in runner.py
        )

        self._server = uvicorn.Server(config)

        # Set up signal handlers if requested
        if self.handle_signals:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self.stop)
        else:
            # Disable uvicorn's internal signal handlers when signals are handled externally
            self._server.install_signal_handlers = False

        try:
            await self._server.serve()
        finally:
            # Clean up tracking Redis connection
            await self._cleanup_tracking()

            # Remove signal handlers
            if self.handle_signals:
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.remove_signal_handler(sig)

    def stop(self) -> None:
        """Signal the API server to stop gracefully (non-blocking)."""
        if self._server:
            self._server.should_exit = True
            logger.debug(f"Signaled API '{self.name}' to stop")

    @property
    def routes(self) -> list[dict[str, Any]]:
        """Get all registered routes."""
        # Include pending routers first to ensure all routes are visible
        self._include_pending_routers()

        result: list[dict[str, Any]] = []
        for route in self.app.routes:
            if hasattr(route, "methods"):
                result.append(
                    {
                        "path": getattr(route, "path", ""),
                        "methods": list(getattr(route, "methods", set())),
                        "name": getattr(route, "name", None),
                    }
                )
        return result

    def __repr__(self) -> str:
        # Use routes property to ensure pending routers are included
        route_count = len(self.routes)
        return (
            f"Api(name={self.name!r}, host={self.host!r}, "
            f"port={self.port}, routes={route_count})"
        )
