"""Conduit CLI."""

import typer

from conduit.cli._console import console
from conduit.cli.call import call
from conduit.cli.list import list_cmd
from conduit.cli.run import run
from conduit.cli.server import (
    db_current as server_db_current,
    db_history as server_db_history,
    db_upgrade as server_db_upgrade,
    start as server_start,
)

app = typer.Typer(
    name="conduit",
    help="Easy background workers and APIs for Python.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        from conduit import __version__

        console.print(f"[bold]conduit[/bold] [dim]{__version__}[/dim]")
        raise typer.Exit()


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
app.command("list")(list_cmd)

server_app = typer.Typer(
    help="Hosted Conduit server commands.",
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
