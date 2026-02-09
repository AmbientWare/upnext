"""Hosted Conduit server commands."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from conduit.cli._console import dim, error_panel, setup_logging, success, warning

if TYPE_CHECKING:
    from alembic.config import Config as AlembicConfig
else:
    AlembicConfig = Any

_REQUIRED_TABLES = {"job_history", "artifacts", "pending_artifacts"}


def _find_server_root_dir() -> Path | None:
    """Resolve source-root server paths from the imported server package."""
    try:
        import server
    except Exception:
        return None

    server_pkg_dir = Path(server.__file__).resolve().parent
    candidate = server_pkg_dir.parent.parent
    if (
        (candidate / "src" / "server" / "main.py").exists()
        and (candidate / "alembic.ini").exists()
        and (candidate / "alembic").is_dir()
    ):
        return candidate
    return None


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
                "Install `conduit-py` (or `conduit-server`) and retry."
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


def _import_server_main() -> Path:
    """
    Import `server.main` and return its package directory for reload.

    Returns:
        Directory containing the imported `server` package.
    """
    try:
        import server.main
        return Path(server.main.__file__).resolve().parent
    except ModuleNotFoundError as e:
        if e.name in {"server", "server.main"}:
            error_panel(
                (
                    "Could not import `server.main:app`. Install `conduit-py` "
                    "(or `conduit-server`) and retry."
                ),
                title="Server import failed",
            )
            raise typer.Exit(1) from e
        error_panel(
            (
                "Could not import `server.main:app` due to a missing dependency. "
                "Install `conduit-py` (or `conduit-server`) and retry."
            ),
            title="Server import failed",
        )
        raise typer.Exit(1) from e
    except Exception as e:
        error_panel(str(e), title="Server import failed")
        raise typer.Exit(1) from e


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
                "Could not locate server migration files. Install `conduit-py` "
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


def _run_alembic_command(
    *,
    database_url: str | None,
    verbose: bool,
    failure_title: str,
    run: Callable[[Any, AlembicConfig], None],
) -> None:
    """Execute an Alembic command with shared env/config/error handling."""
    setup_logging(verbose=verbose)
    _set_server_env(database_url, redis_url=None)

    try:
        from alembic import command

        with _resolve_alembic_config() as cfg:
            run(command, cfg)
    except typer.Exit:
        raise
    except Exception as e:
        error_panel(str(e), title=failure_title)
        raise typer.Exit(1) from e


def _resolve_effective_database_url(database_url: str | None) -> str:
    """Resolve effective database URL from CLI override or server settings."""
    if database_url:
        return database_url

    try:
        from server.config import get_settings
    except Exception as e:
        error_panel(
            (
                "Could not resolve server configuration. "
                "Install `conduit-py` (or `conduit-server`) and retry."
            ),
            title="Server config missing",
        )
        raise typer.Exit(1) from e

    return get_settings().effective_database_url


async def _get_missing_required_tables(database_url: str) -> list[str]:
    """Check required schema tables for a database URL."""
    from server.db.session import Database

    db = Database(database_url)
    await db.connect()
    try:
        return await db.get_missing_tables(_REQUIRED_TABLES)
    finally:
        await db.disconnect()


def _ensure_database_schema_ready(database_url: str | None, *, verbose: bool) -> None:
    """
    Prompt to run migrations before startup when schema is missing tables.

    SQLite is skipped because tables are auto-created in server startup.
    """
    effective_database_url = _resolve_effective_database_url(database_url)
    if effective_database_url.startswith("sqlite"):
        return

    try:
        missing_tables = asyncio.run(_get_missing_required_tables(effective_database_url))
    except Exception as e:
        warning("Could not verify database migration status; continuing startup.")
        if verbose:
            dim(str(e))
        return

    if not missing_tables:
        return

    missing = ", ".join(missing_tables)
    warning(f"Database schema is missing required tables: {missing}")

    try:
        should_migrate = typer.confirm(
            "Run migrations now and then start the server?",
            default=True,
        )
    except typer.Abort as e:
        dim("Exiting without starting server.")
        raise typer.Exit(1) from e

    if not should_migrate:
        dim("Exiting without starting server.")
        raise typer.Exit(0)

    db_upgrade(
        revision="head",
        database_url=effective_database_url,
        verbose=verbose,
    )
    success("Database migrations completed.")


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

    server_pkg_dir = _import_server_main()
    _ensure_database_schema_ready(database_url, verbose=verbose)

    import uvicorn

    try:
        uvicorn.run(
            "server.main:app",
            host=host,
            port=port,
            reload=reload,
            reload_dirs=[str(server_pkg_dir)] if reload else None,
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
    _run_alembic_command(
        database_url=database_url,
        verbose=verbose,
        failure_title="Migration failed",
        run=lambda command, cfg: command.upgrade(cfg, revision),
    )


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
    _run_alembic_command(
        database_url=database_url,
        verbose=verbose,
        failure_title="Failed to read current revision",
        run=lambda command, cfg: command.current(cfg, verbose=verbose),
    )


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
    _run_alembic_command(
        database_url=database_url,
        verbose=verbose,
        failure_title="Failed to read migration history",
        run=lambda command, cfg: command.history(
            cfg, rev_range=rev_range, verbose=verbose, indicate_current=True
        ),
    )
