"""Shared display utilities for CLI commands."""

from collections.abc import Callable

import typer
from rich.box import ROUNDED
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from conduit.cli._console import console, error, nl
from conduit.engine.runner import run_services as run_services  # re-export
from conduit.sdk.api import Api
from conduit.sdk.worker import Worker

# run_services was moved to conduit.engine.runner but re-exported here for backwards compatibility
__all__ = ["run_services", "worker_lines", "print_services_panel", "filter_components"]


def worker_lines(
    worker: Worker,
    *,
    redis_url: str | None,
) -> list[Text]:
    """Build display lines for a worker (name, handlers, queue status)."""
    lines: list[Text] = []

    # Worker name
    line = Text(no_wrap=True, overflow="ellipsis")
    line.append(f"{worker.name}", style="cyan bold")
    lines.append(line)

    # Handler lines
    task_names = list(worker.tasks.keys())
    cron_names = [c.name or c.func.__name__ for c in worker.crons]
    event_patterns = list(worker.events.keys())

    def add_handler_line(label: str, count: int, names: list[str]) -> None:
        line = Text(no_wrap=True, overflow="ellipsis")
        label_text = f"   {label} ({count})"
        line.append(f"{label_text:<18} ", style="bold")
        line.append(", ".join(names), style="dim")
        lines.append(line)

    if task_names:
        add_handler_line("tasks", len(task_names), task_names)
    if cron_names:
        add_handler_line("crons", len(cron_names), cron_names)
    if event_patterns:
        add_handler_line("events", len(event_patterns), event_patterns)

    if not any([task_names, cron_names, event_patterns]):
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append("   no handlers", style="dim")
        lines.append(line)

    # Queue status
    line = Text(no_wrap=True, overflow="ellipsis")
    line.append("   ✓ ", style="green")
    line.append(f"redis ({redis_url})", style="dim")
    lines.append(line)

    return lines


def print_services_panel(
    apis: list[Api],
    workers: list[Worker],
    *,
    title: str,
    worker_line_fn: Callable[[Worker], list[Text]],
) -> None:
    """Print the startup panel showing APIs, workers, and Ctrl+C hint."""
    lines: list[Text] = []

    for api in apis:
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append(f"{api.name}", style="cyan bold")
        line.append(f"  http://{api.host}:{api.port}", style="dim")
        lines.append(line)

    # Blank line between APIs and workers
    if apis and workers:
        lines.append(Text())

    for worker in workers:
        lines.extend(worker_line_fn(worker))

    # Blank line before hint
    lines.append(Text())
    hint = Text(no_wrap=True, overflow="ellipsis")
    hint.append("Press ", style="dim")
    hint.append("Ctrl+C", style="dim bold")
    hint.append(" to stop", style="dim")
    lines.append(hint)

    table = Table.grid(padding=0)
    table.add_column(overflow="ellipsis", no_wrap=True)
    for line in lines:
        table.add_row(line)

    panel = Panel(
        table,
        title=f"[bold]{title}[/bold]",
        title_align="left",
        border_style="dim",
        box=ROUNDED,
        padding=(0, 1),
        expand=False,
    )
    console.print(panel)


def filter_components(
    apis: list[Api],
    workers: list[Worker],
    only: list[str] | None,
) -> tuple[list[Api], list[Worker]]:
    """Filter APIs and workers by name.

    Raises typer.Exit(1) on unknown names or empty result.
    """
    if only:
        only_set = set(only)
        apis = [a for a in apis if a.name in only_set]
        workers = [w for w in workers if w.name in only_set]

        found_names = {a.name for a in apis} | {w.name for w in workers}
        unknown = only_set - found_names
        if unknown:
            nl()
            error(f"Unknown component(s): {', '.join(unknown)}")
            nl()
            raise typer.Exit(1)

    if not apis and not workers:
        nl()
        error("No Api or Worker found in the specified files")
        nl()
        raise typer.Exit(1)

    return apis, workers
