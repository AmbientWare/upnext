"""List components command."""

import typer
from rich.box import ROUNDED
from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from upnext.cli._console import console, dim, error, nl
from upnext.cli._loader import discover_objects


def list_cmd(
    files: list[str] = typer.Argument(..., help="Python files to scan"),
) -> None:
    """List all components in your service."""
    apis, workers = discover_objects(files)

    if not apis and not workers:
        nl()
        error("No components found")
        nl()
        raise typer.Exit(1)

    nl()

    # APIs
    for api in apis:
        route_count = len([r for r in api.app.routes if hasattr(r, "methods")])

        content = Text()
        content.append("API", style="dim")
        content.append(" · ", style="dim")
        content.append(f"http://localhost:{api.port}", style="cyan")
        content.append(" · ", style="dim")
        content.append(f"{route_count} routes", style="dim")

        panel = Panel(
            content,
            title=f"[bold]{api.name}[/bold]",
            title_align="left",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 1),
        )
        console.print(panel)

    # Workers
    for worker in workers:
        lines: list[Text] = []

        # Header line
        header = Text()
        header.append("Worker", style="dim")
        header.append(" · ", style="dim")
        header.append(f"concurrency={worker.concurrency}", style="dim")
        lines.append(header)

        # Tasks
        if worker.tasks:
            lines.append(Text())
            lines.append(Text("Tasks", style="bold"))
            for name, handle in worker.tasks.items():
                line = Text()
                line.append(f"  {name}", style="white")
                opts = []
                if handle.definition.retries:
                    opts.append(f"retries={handle.definition.retries}")
                if handle.definition.timeout:
                    opts.append(f"timeout={handle.definition.timeout}s")
                if opts:
                    line.append(f"  {' · '.join(opts)}", style="dim")
                lines.append(line)

        # Crons
        if worker.crons:
            lines.append(Text())
            lines.append(Text("Crons", style="bold"))
            for cron_def in worker.crons:
                line = Text()
                line.append(f"  {cron_def.display_name}", style="white")
                line.append(f"  {cron_def.schedule}", style="dim")
                lines.append(line)

        # Events
        if worker.events:
            lines.append(Text())
            lines.append(Text("Events", style="bold"))
            for pattern, handle in worker.events.items():
                line = Text()
                line.append(f"  {pattern}", style="white")
                if handle.handler_names:
                    line.append(f"  → {', '.join(handle.handler_names)}", style="dim")
                lines.append(line)

        content = Group(*lines)
        panel = Panel(
            content,
            title=f"[bold]{worker.name}[/bold]",
            title_align="left",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 1),
        )
        console.print(panel)

    # Summary footer
    total_apis = len(apis)
    total_workers = len(workers)
    total_tasks = sum(len(w.tasks) for w in workers)
    total_crons = sum(len(w.crons) for w in workers)
    total_events = sum(len(w.events) for w in workers)

    parts = []
    if total_apis:
        parts.append(f"{total_apis} API{'s' if total_apis != 1 else ''}")
    if total_workers:
        parts.append(f"{total_workers} Worker{'s' if total_workers != 1 else ''}")
    if total_tasks:
        parts.append(f"{total_tasks} task{'s' if total_tasks != 1 else ''}")
    if total_crons:
        parts.append(f"{total_crons} cron{'s' if total_crons != 1 else ''}")
    if total_events:
        parts.append(f"{total_events} event{'s' if total_events != 1 else ''}")

    dim(" · ".join(parts))
    nl()
