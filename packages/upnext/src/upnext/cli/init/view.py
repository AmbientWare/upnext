"""Rich presentation helpers for `upnext init`."""

from __future__ import annotations

from rich.box import ROUNDED
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from upnext.cli._console import console, nl
from upnext.config import settings

_SMALL_CARD_WIDTH = 58


class InitView:
    """Presentation layer for the hosted deploy init flow."""

    def __init__(self, rich_console: Console | None = None) -> None:
        self.console = rich_console or console

    def show_discovery_summary(
        self,
        *,
        entrypoint: str,
        repo_root: str,
        pyproject: str,
        config_path: str,
        overwrite: bool,
    ) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold white", width=11)
        table.add_column(style="bright_white")
        table.add_row("Entrypoint", entrypoint)
        table.add_row("Repo root", repo_root)
        table.add_row("Pyproject", pyproject)
        table.add_row("Config", config_path)
        if overwrite:
            table.add_row("Mode", "[yellow]overwrite existing config[/yellow]")

        panel = Panel(
            table,
            title="[bold]Hosted Deploy Setup[/bold]",
            title_align="left",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 1),
            expand=False,
            width=_SMALL_CARD_WIDTH,
        )
        self.console.print(panel)
        nl()

    def show_component_summary(
        self,
        *,
        api_names: list[str],
        worker_names: list[str],
        discovery_succeeded: bool,
    ) -> None:
        table = Table(box=None, padding=(0, 1), show_header=True)
        table.add_column("Type", style="bold white", width=8)
        table.add_column("Name", style="cyan")

        for name in api_names:
            table.add_row("API", name)
        for name in worker_names:
            table.add_row("Worker", name)

        if not api_names and not worker_names:
            if discovery_succeeded:
                table.add_row("Info", "[dim]No Api or Worker objects found[/dim]")
            else:
                table.add_row(
                    "Info", "[dim]Discovery unavailable in this environment[/dim]"
                )

        panel = Panel(
            table,
            title="[bold]Discovered Components[/bold]",
            title_align="left",
            subtitle=(
                f"[dim]{len(api_names)} API(s) · {len(worker_names)} worker(s)[/dim]"
                if api_names or worker_names
                else None
            ),
            subtitle_align="right",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 1),
            expand=False,
            width=_SMALL_CARD_WIDTH,
        )
        self.console.print(panel)
        nl()

    def show_build_configuration(
        self,
        *,
        python_version: str,
        linux_packages: list[str],
    ) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold white", width=14)
        table.add_column(style="bright_white")
        table.add_row("Python", python_version)
        table.add_row(
            "Linux packages",
            ", ".join(linux_packages) if linux_packages else "(none)",
        )

        panel = Panel(
            table,
            title="[bold]Build Configuration[/bold]",
            title_align="left",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 1),
            expand=False,
            width=_SMALL_CARD_WIDTH,
        )
        self.console.print(panel)

    def show_advanced_section_intro(self) -> None:
        title = Text("Advanced Features", style="bold")
        note = Text(
            "Optional. Leave any prompt blank to keep the value unset.",
            style="dim",
        )
        self.console.print(title)
        self.console.print(note)

    def show_success(
        self,
        *,
        config_path: str,
        entrypoint: str,
        pyproject: str,
        python_version: str,
        linux_packages: list[str],
        api_count: int,
        worker_count: int,
    ) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold white", width=14)
        table.add_column(style="bright_white")
        table.add_row("Config", config_path)
        table.add_row("Entrypoint", entrypoint)
        table.add_row("Pyproject", pyproject)
        table.add_row("Python", python_version)
        table.add_row(
            "Linux packages",
            ", ".join(linux_packages) if linux_packages else "(none)",
        )
        table.add_row("Components", f"{api_count} API(s), {worker_count} worker(s)")

        url = settings.cloud_url
        note = Text.from_markup(
            f"Commit this file and head to [link={url}]{url}[/link] to deploy!",
            style="dim",
        )
        panel = Panel(
            Group(table, Text(), note),
            title="[bold green]Initialization Complete[/bold green]",
            title_align="left",
            border_style="green",
            box=ROUNDED,
            padding=(0, 1),
            expand=False,
            width=_SMALL_CARD_WIDTH,
        )
        self.console.print(panel)
        nl()
