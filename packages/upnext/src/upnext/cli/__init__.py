"""UpNext CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from upnext.cli._console import console
from upnext.cli.call import call
from upnext.cli.health import health
from upnext.cli.init import init
from upnext.cli.inspect import inspect_cmd
from upnext.cli.list import list_cmd
from upnext.cli.run import run

app = typer.Typer(
    name="upnext",
    help="Easy background workers and APIs for Python.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        from upnext import __version__

        console.print(f"[bold]upnext[/bold] [dim]{__version__}[/dim]")
        raise typer.Exit()


def _load_server_command(name: str):
    """Load a server subcommand lazily so non-server CLI usage has no server import dependency."""
    from upnext.cli import server as server_module

    command = getattr(server_module, name, None)
    if not callable(command):
        raise typer.BadParameter(f"Unknown server command: {name}")
    return command


def server_start(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8080, "--port", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
    backend: Annotated[
        str | None,
        typer.Option(
            "--backend",
            envvar="UPNEXT_BACKEND",
            case_sensitive=False,
            help="Persistence backend for hosted server: redis, sqlite, or postgres",
        ),
    ] = None,
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="UPNEXT_DATABASE_URL",
        help="Database URL for the hosted server",
    ),
    redis_url: str | None = typer.Option(
        None,
        "--redis-url",
        envvar="UPNEXT_REDIS_URL",
        help="Redis URL for the hosted server",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    _load_server_command("start")(
        host=host,
        port=port,
        reload=reload,
        backend=backend,
        database_url=database_url,
        redis_url=redis_url,
        verbose=verbose,
    )


def server_db_upgrade(
    revision: str = typer.Argument("head", help="Target Alembic revision"),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="UPNEXT_DATABASE_URL",
        help="Database URL for migrations",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    _load_server_command("db_upgrade")(
        revision=revision,
        database_url=database_url,
        verbose=verbose,
    )


def server_db_current(
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="UPNEXT_DATABASE_URL",
        help="Database URL for migrations",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    _load_server_command("db_current")(
        database_url=database_url,
        verbose=verbose,
    )


def server_db_history(
    rev_range: str | None = typer.Option(
        None,
        "--range",
        help="Revision range (e.g. base:head)",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        envvar="UPNEXT_DATABASE_URL",
        help="Database URL for migrations",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    _load_server_command("db_history")(
        rev_range=rev_range,
        database_url=database_url,
        verbose=verbose,
    )


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    """Background jobs and APIs for Python."""


# Register commands
app.command()(run)
app.command()(call)
app.command()(init)
app.command()(health)
app.command("list")(list_cmd)
app.command("inspect")(inspect_cmd)

server_app = typer.Typer(
    help="Hosted UpNext server commands.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
server_app.command("start")(server_start)

server_db_app = typer.Typer(
    help="Database migration commands for the hosted server.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
server_db_app.command("upgrade")(server_db_upgrade)
server_db_app.command("current")(server_db_current)
server_db_app.command("history")(server_db_history)
server_app.add_typer(server_db_app, name="db")

app.add_typer(server_app, name="server")
