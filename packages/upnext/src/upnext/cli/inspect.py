"""Inspect components command — shows all registered APIs, workers, and static mounts."""

import json as json_mod

import typer
from rich.box import ROUNDED
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from upnext.cli._console import console, dim, error, nl
from upnext.cli._loader import discover_objects


def inspect_cmd(
    files: list[str] = typer.Argument(..., help="Python files to inspect"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Inspect all components and their configuration."""
    apis, workers = discover_objects(files)

    if not apis and not workers:
        if json:
            print(json_mod.dumps({"apis": [], "workers": []}))
            return
        nl()
        error("No components found")
        nl()
        raise typer.Exit(1)

    if json:
        _print_json(apis, workers)
    else:
        _print_rich(apis, workers)


def _print_json(apis: list, workers: list) -> None:
    """Output machine-readable JSON for the deploy pipeline."""
    data = {
        "apis": [],
        "workers": [],
    }

    for api in apis:
        routes = []
        for route in api.app.routes:
            if hasattr(route, "methods"):
                path = getattr(route, "path", "")
                if path.startswith("/runtime/"):
                    continue
                for method in getattr(route, "methods", set()):
                    routes.append(f"{method}:{path}")

        static_mounts = []
        for mount in api.static_mounts:
            static_mounts.append({
                "path": mount.path,
                "directory": mount.directory,
                "package_manager": mount.package_manager.value if mount.package_manager else None,
                "runtime_version": mount.runtime_version,
                "build_command": mount.build_command,
                "dev_command": mount.dev_command,
                "output": mount.output,
                "spa": mount.spa,
            })

        data["apis"].append({
            "name": api.name,
            "port": api.port,
            "routes": sorted(routes),
            "static_mounts": static_mounts,
        })

    for worker in workers:
        tasks = []
        for name, handle in worker.tasks.items():
            task_info: dict = {"name": name}
            if handle.definition.retries:
                task_info["retries"] = handle.definition.retries
            if handle.definition.timeout:
                task_info["timeout"] = handle.definition.timeout
            tasks.append(task_info)

        crons = []
        for cron_def in worker.crons:
            crons.append({
                "name": cron_def.display_name,
                "schedule": cron_def.schedule,
            })

        events = list(worker.events.keys())

        data["workers"].append({
            "name": worker.name,
            "concurrency": worker.concurrency,
            "tasks": tasks,
            "crons": crons,
            "events": events,
        })

    print(json_mod.dumps(data, indent=2))


def _print_rich(apis: list, workers: list) -> None:
    """Output pretty Rich panels for user inspection."""
    nl()

    for api in apis:
        lines: list[Text] = []

        # Header
        header = Text()
        header.append("API", style="dim")
        header.append(" · ", style="dim")
        header.append(f"http://localhost:{api.port}", style="cyan")
        lines.append(header)

        # Routes
        routes = [
            r
            for r in api.app.routes
            if hasattr(r, "methods") and not getattr(r, "path", "").startswith("/runtime/")
        ]
        if routes:
            lines.append(Text())
            lines.append(Text("Routes", style="bold"))
            for route in routes:
                path = getattr(route, "path", "")
                methods = sorted(getattr(route, "methods", set()))
                for method in methods:
                    line = Text()
                    line.append(f"  {method:<6} ", style="green")
                    line.append(path, style="white")
                    lines.append(line)

        # Static mounts
        if api.static_mounts:
            lines.append(Text())
            lines.append(Text("Static", style="bold"))
            for mount in api.static_mounts:
                line = Text()
                line.append(f"  {mount.path}", style="white")
                line.append(" → ", style="dim")
                line.append(mount.directory, style="cyan")

                tags = []
                if mount.package_manager:
                    tags.append(mount.package_manager.value)
                if mount.spa:
                    tags.append("spa")
                if tags:
                    line.append(f"  ({', '.join(tags)})", style="dim")
                lines.append(line)

                if mount.build_command:
                    detail = Text()
                    detail.append("    build: ", style="dim")
                    detail.append(mount.build_command, style="white")
                    if mount.output:
                        detail.append(" → ", style="dim")
                        detail.append(mount.output, style="cyan")
                    lines.append(detail)

                if mount.dev_command:
                    detail = Text()
                    detail.append("    dev: ", style="dim")
                    detail.append(mount.dev_command, style="white")
                    lines.append(detail)

        content = Group(*lines)
        panel = Panel(
            content,
            title=f"[bold]{api.name}[/bold]",
            title_align="left",
            border_style="dim",
            box=ROUNDED,
            padding=(0, 1),
        )
        console.print(panel)

    for worker in workers:
        lines: list[Text] = []

        # Header
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

    # Summary
    total_apis = len(apis)
    total_workers = len(workers)
    total_tasks = sum(len(w.tasks) for w in workers)
    total_crons = sum(len(w.crons) for w in workers)
    total_events = sum(len(w.events) for w in workers)
    total_static = sum(len(a.static_mounts) for a in apis)

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
    if total_static:
        parts.append(f"{total_static} static mount{'s' if total_static != 1 else ''}")

    dim(" · ".join(parts))
    nl()
