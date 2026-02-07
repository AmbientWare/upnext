"""Hosted Conduit server commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from conduit.cli._console import error_panel, setup_logging


def _find_server_src_dir() -> Path | None:
    """Best-effort resolution of packages/server/src in monorepo checkouts."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "packages" / "server" / "src"
        if (candidate / "server" / "main.py").exists():
            return candidate
    return None


def start(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8080, "--port", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="CONDUIT_DATABASE_URL",
        help="Database URL for the hosted server",
    ),
    redis_url: str | None = typer.Option(
        None,
        "--redis-url",
        envvar="CONDUIT_REDIS_URL",
        help="Redis URL for the hosted server",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """
    Start the hosted Conduit server (packages/server).
    """
    setup_logging(verbose=verbose)

    if database_url:
        os.environ["CONDUIT_DATABASE_URL"] = database_url
    if redis_url:
        os.environ["CONDUIT_REDIS_URL"] = redis_url

    server_src_dir = _find_server_src_dir()
    if server_src_dir and str(server_src_dir) not in sys.path:
        sys.path.insert(0, str(server_src_dir))

    try:
        import server.main  # noqa: F401
    except Exception as e:
        error_panel(
            (
                "Could not import `server.main:app`. "
                "Run this from the conduit monorepo root or ensure packages/server is on PYTHONPATH."
            ),
            title="Server import failed",
        )
        raise typer.Exit(1) from e

    import uvicorn

    try:
        uvicorn.run(
            "server.main:app",
            host=host,
            port=port,
            reload=reload,
            reload_dirs=[str(server_src_dir)] if reload and server_src_dir else None,
        )
    except Exception as e:
        error_panel(str(e), title="Server start failed")
        raise typer.Exit(1) from e
