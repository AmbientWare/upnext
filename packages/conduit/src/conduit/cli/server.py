"""Hosted Conduit server commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from conduit.cli._console import error_panel, setup_logging


def _find_server_root_dir() -> Path | None:
    """Best-effort resolution of packages/server in monorepo checkouts."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "packages" / "server"
        if (candidate / "src" / "server" / "main.py").exists():
            return candidate
    return None


def _find_server_src_dir() -> Path | None:
    """Best-effort resolution of packages/server/src in monorepo checkouts."""
    server_root = _find_server_root_dir()
    if server_root is None:
        return None
    return server_root / "src"


def _set_server_env(database_url: str | None, redis_url: str | None) -> None:
    """Set server-related env vars for child imports/commands."""
    if database_url:
        os.environ["CONDUIT_DATABASE_URL"] = database_url
        # Alembic env.py currently reads DATABASE_URL.
        os.environ["DATABASE_URL"] = database_url
    if redis_url:
        os.environ["CONDUIT_REDIS_URL"] = redis_url


def _build_alembic_config(server_root: Path):
    """Build Alembic config with absolute paths so command works from any cwd."""
    try:
        from alembic.config import Config
    except Exception as e:
        error_panel(
            (
                "Alembic is not available in this environment. "
                "Install server dependencies (e.g. `uv sync --package conduit-server`) and retry."
            ),
            title="Alembic not installed",
        )
        raise typer.Exit(1) from e

    alembic_ini = server_root / "alembic.ini"
    if not alembic_ini.exists():
        error_panel(
            f"Alembic config not found at {alembic_ini}",
            title="Server config missing",
        )
        raise typer.Exit(1)

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(server_root / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(server_root / "src"))
    return cfg


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

    _set_server_env(database_url, redis_url)

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


def db_upgrade(
    revision: str = typer.Argument("head", help="Target Alembic revision"),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="CONDUIT_DATABASE_URL",
        help="Database URL for migrations",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Run Alembic upgrade for the hosted Conduit server schema."""
    setup_logging(verbose=verbose)
    _set_server_env(database_url, redis_url=None)

    server_root = _find_server_root_dir()
    if server_root is None:
        error_panel(
            "Could not locate packages/server in this workspace.",
            title="Server package missing",
        )
        raise typer.Exit(1)

    cfg = _build_alembic_config(server_root)

    try:
        from alembic import command

        command.upgrade(cfg, revision)
    except Exception as e:
        error_panel(str(e), title="Migration failed")
        raise typer.Exit(1) from e


def db_current(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="CONDUIT_DATABASE_URL",
        help="Database URL for migrations",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Show current Alembic revision for the hosted server database."""
    setup_logging(verbose=verbose)
    _set_server_env(database_url, redis_url=None)

    server_root = _find_server_root_dir()
    if server_root is None:
        error_panel(
            "Could not locate packages/server in this workspace.",
            title="Server package missing",
        )
        raise typer.Exit(1)

    cfg = _build_alembic_config(server_root)

    try:
        from alembic import command

        command.current(cfg, verbose=verbose)
    except Exception as e:
        error_panel(str(e), title="Failed to read current revision")
        raise typer.Exit(1) from e


def db_history(
    rev_range: str | None = typer.Option(
        None,
        "--range",
        help="Revision range (e.g. base:head)",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="CONDUIT_DATABASE_URL",
        help="Database URL for migrations",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Show Alembic revision history for the hosted server schema."""
    setup_logging(verbose=verbose)
    _set_server_env(database_url, redis_url=None)

    server_root = _find_server_root_dir()
    if server_root is None:
        error_panel(
            "Could not locate packages/server in this workspace.",
            title="Server package missing",
        )
        raise typer.Exit(1)

    cfg = _build_alembic_config(server_root)

    try:
        from alembic import command

        command.history(cfg, rev_range=rev_range, verbose=verbose, indicate_current=True)
    except Exception as e:
        error_panel(str(e), title="Failed to read migration history")
        raise typer.Exit(1) from e
