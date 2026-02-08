"""Hosted Conduit server commands."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from conduit.cli._console import error_panel, setup_logging

if TYPE_CHECKING:
    from alembic.config import Config as AlembicConfig
else:
    AlembicConfig = Any


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


def _find_packaged_alembic_paths() -> tuple[Traversable, Traversable] | None:
    """Resolve migration assets packaged inside conduit-server."""
    try:
        server_pkg = resources.files("server")
    except Exception:
        return None

    alembic_ini = server_pkg.joinpath("_alembic.ini")
    alembic_dir = server_pkg.joinpath("_alembic")
    if not alembic_ini.is_file() or not alembic_dir.is_dir():
        return None
    return alembic_ini, alembic_dir


def _set_server_env(database_url: str | None, redis_url: str | None) -> None:
    """Set server-related env vars for child imports/commands."""
    if database_url:
        os.environ["CONDUIT_DATABASE_URL"] = database_url
        # Alembic env.py currently reads DATABASE_URL.
        os.environ["DATABASE_URL"] = database_url
    if redis_url:
        os.environ["CONDUIT_REDIS_URL"] = redis_url


def _build_alembic_config(
    server_root: Path | None = None,
    *,
    alembic_ini: Path | None = None,
    script_location: Path | None = None,
    prepend_sys_path: Path | None = None,
) -> AlembicConfig:
    """Build Alembic config with absolute paths so command works from any cwd."""
    try:
        from alembic.config import Config
    except Exception as e:
        error_panel(
            (
                "Alembic is not available in this environment. "
                "Install `conduit-py[server]` (or `conduit-server`) and retry."
            ),
            title="Alembic not installed",
        )
        raise typer.Exit(1) from e

    if server_root is not None:
        alembic_ini = server_root / "alembic.ini"
        script_location = server_root / "alembic"
        prepend_sys_path = server_root / "src"

    if alembic_ini is None or script_location is None:
        raise ValueError("alembic_ini and script_location are required")

    if not alembic_ini.exists():
        error_panel(
            f"Alembic config not found at {alembic_ini}",
            title="Server config missing",
        )
        raise typer.Exit(1)

    if not script_location.exists():
        error_panel(
            f"Alembic scripts not found at {script_location}",
            title="Server config missing",
        )
        raise typer.Exit(1)

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(script_location))
    if prepend_sys_path is not None:
        cfg.set_main_option("prepend_sys_path", str(prepend_sys_path))
    return cfg


def _import_server_main() -> Path | None:
    """
    Import `server.main`, preferring installed package import.

    Returns:
        Monorepo server src path when fallback path injection was used, otherwise None.
    """
    try:
        import server.main  # noqa: F401
        return None
    except ModuleNotFoundError as e:
        # Fallback to monorepo source only when the server package itself is missing.
        if e.name not in {"server", "server.main"}:
            error_panel(
                (
                    "Could not import `server.main:app` due to a missing dependency. "
                    "Install `conduit-py[server]` (or `conduit-server`) and retry."
                ),
                title="Server import failed",
            )
            raise typer.Exit(1) from e
    except Exception as e:
        error_panel(str(e), title="Server import failed")
        raise typer.Exit(1) from e

    server_src_dir = _find_server_src_dir()
    if server_src_dir and str(server_src_dir) not in sys.path:
        sys.path.insert(0, str(server_src_dir))

    try:
        import server.main  # noqa: F401
    except Exception as e:
        error_panel(
            (
                "Could not import `server.main:app`. Install `conduit-py[server]` "
                "(or `conduit-server`). In a source checkout, run "
                "`uv sync --all-packages --all-groups`."
            ),
            title="Server import failed",
        )
        raise typer.Exit(1) from e

    return server_src_dir


@contextmanager
def _resolve_alembic_config() -> Iterator[AlembicConfig]:
    """Resolve Alembic config from monorepo paths or packaged migration assets."""
    server_root = _find_server_root_dir()
    if server_root is not None:
        yield _build_alembic_config(server_root=server_root)
        return

    packaged_paths = _find_packaged_alembic_paths()
    if packaged_paths is None:
        error_panel(
            (
                "Could not locate server migration files. Install `conduit-py[server]` "
                "(or `conduit-server`). In a source checkout, run "
                "`uv sync --all-packages --all-groups`."
            ),
            title="Server migrations missing",
        )
        raise typer.Exit(1)

    alembic_ini_res, alembic_dir_res = packaged_paths
    with ExitStack() as stack:
        alembic_ini_path = Path(stack.enter_context(resources.as_file(alembic_ini_res)))
        alembic_dir_path = Path(stack.enter_context(resources.as_file(alembic_dir_res)))
        yield _build_alembic_config(
            alembic_ini=alembic_ini_path,
            script_location=alembic_dir_path,
        )


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
    Start the hosted Conduit server.
    """
    setup_logging(verbose=verbose)

    _set_server_env(database_url, redis_url)

    server_src_dir = _import_server_main()

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

    try:
        from alembic import command

        with _resolve_alembic_config() as cfg:
            command.upgrade(cfg, revision)
    except typer.Exit:
        raise
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

    try:
        from alembic import command

        with _resolve_alembic_config() as cfg:
            command.current(cfg, verbose=verbose)
    except typer.Exit:
        raise
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

    try:
        from alembic import command

        with _resolve_alembic_config() as cfg:
            command.history(
                cfg, rev_range=rev_range, verbose=verbose, indicate_current=True
            )
    except typer.Exit:
        raise
    except Exception as e:
        error_panel(str(e), title="Failed to read migration history")
        raise typer.Exit(1) from e
