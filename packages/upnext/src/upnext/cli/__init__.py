"""UpNext CLI."""

import typer

from upnext.cli._console import console
from upnext.cli.call import call
from upnext.cli.list import list_cmd
from upnext.cli.run import run
from upnext.cli.server import (
    db_current as server_db_current,
)
from upnext.cli.server import (
    db_history as server_db_history,
)
from upnext.cli.server import (
    db_upgrade as server_db_upgrade,
)
from upnext.cli.server import (
    start as server_start,
)

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
