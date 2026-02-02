"""
Api class that wraps FastAPI for HTTP endpoints.

This is the user-facing Api that supports @api.get(), @api.post(), etc.
"""

import asyncio
import logging
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

import uvicorn
from fastapi import APIRouter, FastAPI

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
    debug: bool = field(
        default_factory=lambda: os.environ.get("CONDUIT_DEBUG", "").lower() == "true"
    )

    # Signal handling (set to False when signals are handled at a higher level)
    handle_signals: bool = True

    # Internal FastAPI app (created lazily)
    _app: FastAPI | None = field(default=None, init=False)
    _server: Any = field(default=None, init=False)
    _pending_routers: list[tuple["APIRouter", dict[str, Any]]] = field(
        default_factory=list, init=False
    )

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

    async def start(self) -> None:
        """
        Start the API server.

        This runs uvicorn to serve the FastAPI application.
        If handle_signals is True (default), SIGINT/SIGTERM will trigger graceful shutdown.
        """

        # Include any pending routers before starting
        self._include_pending_routers()

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
