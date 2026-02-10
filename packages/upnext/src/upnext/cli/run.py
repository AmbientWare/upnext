"""Run command for UpNext services."""

import asyncio

import typer

from upnext.cli._console import error_panel, nl, setup_logging
from upnext.cli._display import (
    filter_components,
    print_services_panel,
    run_services,
    worker_lines,
)
from upnext.cli._loader import discover_objects


def run(
    files: list[str] = typer.Argument(..., help="Python files containing services"),
    redis_url: str | None = typer.Option(
        None,
        "--redis-url",
        help="Redis URL (overrides UPNEXT_REDIS_URL and worker config)",
    ),
    only: list[str] = typer.Option(
        None,
        "--only",
        "-o",
        help="Only run specific components by name (e.g., --only my-api --only my-worker)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """
    Run UpNext services (APIs and Workers).

    Examples:
        upnext run service.py                    # Run all APIs and Workers
        upnext run service.py --redis-url redis://localhost:6379
        upnext run service.py -o api -o worker   # Run 'api' and 'worker'
    """
    setup_logging(verbose=verbose)

    apis, workers = discover_objects(files)
    apis, workers = filter_components(apis, workers, only)

    try:
        for w in workers:
            w.initialize(redis_url)
    except ValueError as e:
        error_panel(str(e), title="Configuration error")
        raise typer.Exit(1)

    # Determine redis URL for display (from first worker that has one, or first API)
    display_redis_url = next(
        (w.resolved_redis_url for w in workers if w.resolved_redis_url), None
    ) or next((a.redis_url for a in apis if a.redis_url), None)

    print_services_panel(
        apis,
        workers,
        title="upnext",
        worker_line_fn=lambda w: worker_lines(w),
        redis_url=display_redis_url,
    )

    try:
        asyncio.run(run_services(apis, workers))
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl+C
    finally:
        nl()
