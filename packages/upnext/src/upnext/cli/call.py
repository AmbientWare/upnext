"""Call command for running a single function."""

import asyncio
import json
import time
from typing import Any

import typer
from rich.box import ROUNDED
from rich.panel import Panel
from rich.text import Text

from upnext.cli._console import console, error, error_panel, nl, setup_logging
from upnext.cli._loader import discover_objects
from upnext.config import get_settings
from upnext.sdk.worker import Worker


def call(
    file: str = typer.Argument(..., help="Python file containing the worker"),
    function: str = typer.Argument(..., help="Function name to call"),
    redis_url: str | None = typer.Option(
        None,
        "--redis-url",
        help="Redis URL (overrides UPNEXT_REDIS_URL and worker config)",
    ),
    args: list[str] = typer.Argument(None, help="Arguments as key=value pairs"),
    json_args: str = typer.Option(
        None,
        "--json",
        "-j",
        help="Arguments as JSON string",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """
    Call a single task function directly.

    Examples:
        upnext call service.py process_order order_id=123
        upnext call service.py send_email to=user@example.com subject="Hello"
        upnext call service.py process_order --json '{"order_id": "123"}'
    """
    setup_logging(verbose=verbose)

    # Parse arguments
    kwargs: dict[str, Any] = {}

    if json_args:
        try:
            kwargs = json.loads(json_args)
        except json.JSONDecodeError as e:
            error(f"Invalid JSON: {e}")
            raise typer.Exit(1)
    elif args:
        for arg in args:
            if "=" not in arg:
                error(f"Invalid argument format: {arg} (expected key=value)")
                raise typer.Exit(1)
            key, value = arg.split("=", 1)
            # Try to parse as JSON for complex types
            try:
                kwargs[key] = json.loads(value)
            except json.JSONDecodeError:
                kwargs[key] = value

    # Discover workers
    _, workers = discover_objects([file])

    if not workers:
        error(f"No workers found in {file}")
        raise typer.Exit(1)

    # Find the function
    target_worker = None
    task_handle = None

    for worker in workers:
        if function in worker.tasks:
            target_worker = worker
            task_handle = worker.tasks[function]
            break

    if not target_worker or not task_handle:
        # List available functions
        all_functions: list[str] = []
        for worker in workers:
            all_functions.extend(worker.tasks.keys())

        error(f"Function '{function}' not found")
        if all_functions:
            nl()
            console.print("Available functions:", style="dim")
            for fn in sorted(all_functions):
                console.print(f"  {fn}", style="dim")
        raise typer.Exit(1)

    # Initialize worker (resolves redis_url, creates client)
    try:
        target_worker.initialize(redis_url)
    except ValueError as e:
        error_panel(str(e), title="Configuration error")
        raise typer.Exit(1)

    # Check connection status for display
    api_url = get_settings().url

    # Show what we're running
    nl()
    _print_call_panel(
        function, kwargs, target_worker.name, target_worker.resolved_redis_url, api_url
    )

    try:
        start_time = time.time()
        result = asyncio.run(_call_function(target_worker, function, kwargs))
        duration_ms = (time.time() - start_time) * 1000

        _print_result_panel(result, duration_ms)

    except Exception as e:
        error_panel(str(e))
        if verbose:
            console.print_exception()
        raise typer.Exit(1)


def _print_call_panel(
    function: str,
    kwargs: dict[str, Any],
    worker_name: str,
    redis_url: str | None,
    api_url: str | None,
) -> None:
    """Print the call info panel."""
    lines: list[Text] = []

    # Function name
    line = Text()
    line.append(function, style="cyan bold")
    lines.append(line)

    # Arguments
    if kwargs:
        line = Text()
        line.append("  args   ", style="bold")
        args_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
        if len(args_str) > 40:
            args_str = args_str[:37] + "..."
        line.append(args_str, style="dim")
        lines.append(line)

    # Worker
    line = Text()
    line.append("  worker ", style="bold")
    line.append(worker_name, style="dim")
    lines.append(line)

    # Redis status
    line = Text()
    line.append("  redis  ", style="bold")
    line.append(f"✓ {redis_url}", style="green")
    lines.append(line)

    # API status
    line = Text()
    line.append("  api    ", style="bold")
    if api_url:
        line.append(f"✓ {api_url}", style="green")
    else:
        line.append("local mode", style="dim")
    lines.append(line)

    panel = Panel(
        Text("\n").join(lines),
        title="[bold]upnext call[/bold]",
        title_align="left",
        border_style="dim",
        box=ROUNDED,
        padding=(0, 1),
        expand=False,
    )
    console.print(panel)


def _print_result_panel(result: Any, duration_ms: float) -> None:
    """Print the result panel."""
    lines: list[Text] = []

    # Status
    line = Text()
    line.append("✓ ", style="green bold")
    line.append(f"Completed in {duration_ms:.0f}ms", style="green")
    lines.append(line)

    # Result
    if result is not None:
        lines.append(Text())
        line = Text()
        line.append("Result ", style="bold")
        if isinstance(result, (dict, list)):
            result_str = json.dumps(result, default=str, indent=2)
            for result_line in result_str.split("\n"):
                lines.append(Text(result_line, style="dim"))
        else:
            line.append(str(result), style="dim")
            lines.append(line)

    panel = Panel(
        Text("\n").join(lines),
        border_style="green dim",
        box=ROUNDED,
        padding=(0, 1),
        expand=False,
    )
    console.print(panel)
    nl()


async def _call_function(
    worker: Worker,
    function_name: str,
    kwargs: dict[str, Any],
) -> Any:
    """Execute function using the worker's execute() method."""
    return await worker.execute(function_name, kwargs)
