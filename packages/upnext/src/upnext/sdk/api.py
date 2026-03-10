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
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, TypeVar

from fastapi.responses import JSONResponse
import redis.asyncio as aioredis
import uvicorn
from fastapi import APIRouter, FastAPI
from shared.keys import API_INSTANCE_TTL, api_instance_key

from upnext.config import get_settings
from upnext.sdk.health import HEARTBEAT_INTERVAL_SECONDS, touch_health_file
from upnext.sdk.middleware import ApiTrackingConfig, ApiTrackingMiddleware

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class PackageManager(StrEnum):
    """Package manager for building static frontend assets."""

    BUN = "bun"
    NPM = "npm"
    YARN = "yarn"
    PNPM = "pnpm"


# Keep old name as alias for backward compatibility
StaticRuntime = PackageManager

_DEFAULT_BUILD_COMMANDS: dict[PackageManager, str] = {
    PackageManager.BUN: "bun run build",
    PackageManager.NPM: "npm run build",
    PackageManager.YARN: "yarn build",
    PackageManager.PNPM: "pnpm build",
}

_DEFAULT_DEV_COMMANDS: dict[PackageManager, str] = {
    PackageManager.BUN: "bun dev",
    PackageManager.NPM: "npm run dev",
    PackageManager.YARN: "yarn dev",
    PackageManager.PNPM: "pnpm dev",
}

_DEFAULT_RUNTIME_VERSIONS: dict[PackageManager, str] = {
    PackageManager.BUN: "1",
    PackageManager.NPM: "22",
    PackageManager.YARN: "22",
    PackageManager.PNPM: "22",
}

_INSTALL_COMMANDS: dict[PackageManager, str] = {
    PackageManager.BUN: "bun install --frozen-lockfile",
    PackageManager.NPM: "npm ci",
    PackageManager.YARN: "yarn install --frozen-lockfile",
    PackageManager.PNPM: "corepack enable && pnpm install --frozen-lockfile",
}


@dataclass
class StaticMount:
    """Configuration for serving static frontend assets from an Api."""

    path: str
    directory: str
    package_manager: PackageManager | None = None
    runtime_version: str | None = None
    build_command: str | None = None
    dev_command: str | None = None
    output: str | None = None
    spa: bool = True

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError(f"Static mount path must start with '/': {self.path!r}")
        if ".." in Path(self.directory).parts:
            raise ValueError(f"Static mount directory must not contain '..': {self.directory!r}")
        if self.package_manager:
            if self.build_command is None:
                self.build_command = _DEFAULT_BUILD_COMMANDS[self.package_manager]
            if self.dev_command is None:
                self.dev_command = _DEFAULT_DEV_COMMANDS[self.package_manager]
            if self.runtime_version is None:
                self.runtime_version = _DEFAULT_RUNTIME_VERSIONS[self.package_manager]
        if self.build_command and not self.package_manager:
            raise ValueError("package_manager is required when build_command is specified")
        if self.build_command and not self.output:
            raise ValueError("output is required when build_command is specified")

    @property
    def serve_directory(self) -> str:
        """The directory to serve at runtime (output if set, else directory)."""
        return self.output or self.directory

    @property
    def install_command(self) -> str | None:
        """The dependency install command for this package manager."""
        return _INSTALL_COMMANDS.get(self.package_manager) if self.package_manager else None


@dataclass
class Api:
    """
    User-facing Api class that wraps FastAPI.

    Example:
        import upnext

        api = upnext.Api("my-api")

        @api.get("/health")
        async def health():
            return {"status": "ok"}

        @api.post("/orders")
        async def create_order(data: dict):
            return {"id": "123", "status": "created"}

        # Run with: upnext dev service.py
    """

    name: str
    host: str = "0.0.0.0"
    port: int = 8000
    docs_url: str = "/docs"
    openapi_url: str = "/openapi.json"
    debug: bool = field(default_factory=lambda: get_settings().debug)

    # Redis URL for API request tracking (auto-detected from upnext_REDIS_URL)
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
    _workspace_id: str = field(
        default_factory=lambda: get_settings().normalized_workspace_id,
        init=False,
    )
    _pending_routers: list[tuple["APIRouter", dict[str, Any]]] = field(
        default_factory=list, init=False
    )
    _static_mounts: list[StaticMount] = field(default_factory=list, init=False)

    @property
    def api_id(self) -> str | None:
        """Get the unique instance ID (generated on start)."""
        return self._api_id

    @property
    def static_mounts(self) -> list[StaticMount]:
        """Get registered static mounts."""
        return list(self._static_mounts)

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

    @classmethod
    def from_fastapi(
        cls,
        app: FastAPI,
        *,
        name: str | None = None,
        **kwargs: Any,
    ) -> "Api":
        """Adopt an existing FastAPI app and manage it with UpNext.

        Additional keyword arguments are forwarded to ``Api`` construction
        (for example ``host``, ``port``, ``redis_url``).
        """
        api = cls(name=name or app.title or "upnext-api", **kwargs)
        api._app = app
        return api

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

    def static(
        self,
        path: str,
        *,
        directory: str,
        package_manager: PackageManager | None = None,
        runtime_version: str | None = None,
        build_command: str | None = None,
        dev_command: str | None = None,
        output: str | None = None,
        spa: bool = True,
    ) -> None:
        """
        Serve static frontend assets (SPA or plain files).

        When ``package_manager`` is set, ``build_command``, ``dev_command``, and
        ``runtime_version`` are derived automatically. Pass explicit values to override.

        Example:
            # React app — defaults to bun run build / bun dev
            api.static(
                "/",
                directory="./frontend",
                package_manager=PackageManager.BUN,
                output="./frontend/dist",
            )

            # Plain static directory (no build)
            api.static("/docs", directory="./public", spa=False)
        """
        mount = StaticMount(
            path=path,
            directory=directory,
            package_manager=package_manager,
            runtime_version=runtime_version,
            build_command=build_command,
            dev_command=dev_command,
            output=output,
            spa=spa,
        )
        if any(m.path == path for m in self._static_mounts):
            raise ValueError(f"Static mount already registered for path: {path!r}")
        self._static_mounts.append(mount)

    def _include_pending_routers(self) -> None:
        """Include all pending routers in the app (called before start)."""
        for router, kwargs in self._pending_routers:
            self.app.include_router(router, **kwargs)
        self._pending_routers.clear()

    def _mount_static(self) -> None:
        """Mount static file directories registered via static()."""
        from starlette.responses import FileResponse
        from starlette.staticfiles import StaticFiles

        # Sort so path="/" is mounted last — API routes take priority
        sorted_mounts = sorted(
            self._static_mounts,
            key=lambda m: (m.path == "/", m.path),
        )

        for mount in sorted_mounts:
            serve_dir = Path(mount.serve_directory).resolve()

            if not serve_dir.exists():
                logger.warning(
                    f"Static directory does not exist: {serve_dir} "
                    f"(mount path: {mount.path})"
                )
                continue

            if mount.spa:
                # SPA mode: serve static files, catch-all returns index.html
                mount_prefix = mount.path.rstrip("/")
                index_file = serve_dir / "index.html"

                # Catch-all route: serve matching files, fallback to index.html
                @self.app.get(f"{mount_prefix}/{{full_path:path}}")
                async def serve_spa(
                    full_path: str,
                    _serve_dir: Path = serve_dir,
                    _index: Path = index_file,
                ) -> FileResponse:
                    from starlette.responses import Response

                    file_path = (_serve_dir / full_path).resolve()
                    if file_path.is_relative_to(_serve_dir) and file_path.is_file():
                        return FileResponse(file_path)
                    if _index.is_file():
                        return FileResponse(_index)
                    return Response(status_code=404)
            else:
                # Plain static directory mount
                self.app.mount(
                    mount.path,
                    StaticFiles(directory=serve_dir),
                    name=f"static-{mount.path}",
                )

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

        # Generate unique instance ID and register in Redis
        self._api_id = f"api_{uuid.uuid4().hex[:8]}"
        self._started_at = datetime.now(UTC)

        settings = get_settings()
        self.app.add_middleware(
            ApiTrackingMiddleware,
            api_name=self.name,
            redis_client=self._redis,
            api_instance_id=self._api_id,
            config=ApiTrackingConfig(
                normalize_paths=settings.api_tracking_normalize_paths,
                registry_refresh_seconds=settings.api_tracking_registry_refresh_seconds,
                request_events_enabled=settings.api_request_events_enabled,
                request_events_sample_rate=settings.api_request_events_sample_rate,
                request_events_slow_ms=settings.api_request_events_slow_ms,
                request_events_stream_max_len=settings.api_request_events_stream_max_len,
            ),
        )

        await self._write_instance_heartbeat()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.debug(f"API instance registered: {self._api_id}")

    def _get_endpoint_list(self) -> list[str]:
        """Get list of registered endpoint strings (e.g. 'GET:/health').

        Excludes built-in /runtime/* endpoints from the reported list.
        """
        endpoints: list[str] = []
        for route in self.app.routes:
            if hasattr(route, "methods"):
                path = getattr(route, "path", "")
                if path.startswith("/runtime/"):
                    continue
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
        key = api_instance_key(self._api_id, workspace_id=self._workspace_id)
        await self._redis.setex(key, API_INSTANCE_TTL, self._instance_data())

    async def _heartbeat_loop(self) -> None:
        """Refresh instance TTL in Redis periodically."""
        touch_health_file()
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                await self._write_instance_heartbeat()
                touch_health_file()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"API heartbeat error: {e}")
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

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
                    await self._redis.delete(
                        api_instance_key(
                            self._api_id,
                            workspace_id=self._workspace_id,
                        )
                    )
                except Exception:
                    pass

            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    def _register_runtime_routes(self) -> None:
        """Register built-in /runtime/health and /runtime/ready endpoints."""
        runtime_router = APIRouter(prefix="/runtime", tags=["runtime"])

        @runtime_router.get("/health")
        async def runtime_health() -> dict[str, str]:
            """Liveness probe — returns 200 if the process is alive."""
            return {"status": "ok"}

        @runtime_router.get("/ready")
        async def runtime_ready() -> Any:
            """Readiness probe — returns 503 if Redis is unavailable."""

            if self._redis is None and self.redis_url:
                return JSONResponse(
                    status_code=503,
                    content={"status": "degraded", "reason": "redis_unavailable"},
                )
            return {"status": "ready"}

        self.app.include_router(runtime_router)

    async def start(self) -> None:
        """
        Start the API server.

        This runs uvicorn to serve the FastAPI application.
        If handle_signals is True (default), SIGINT/SIGTERM will trigger graceful shutdown.
        """

        # Register built-in health endpoints before user routes
        self._register_runtime_routes()

        # Include any pending routers before starting
        self._include_pending_routers()

        # Mount static file directories (after routers so API routes take priority)
        if self._static_mounts:
            self._mount_static()

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
