"""Run command for Conduit services."""

import asyncio

import typer

from conduit.cli._console import error_panel, nl, setup_logging
from conduit.cli._display import (
    filter_components,
    print_services_panel,
    run_services,
    worker_lines,
)
from conduit.cli._loader import discover_objects


def run(
    files: list[str] = typer.Argument(..., help="Python files containing services"),
    redis_url: str | None = typer.Option(
        None,
        "--redis-url",
        help="Redis URL (overrides CONDUIT_REDIS_URL and worker config)",
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
    Run Conduit services (APIs and Workers).

    Examples:
        conduit run service.py                    # Run all APIs and Workers
        conduit run service.py --redis-url redis://localhost:6379
        conduit run service.py -o api -o worker   # Run 'api' and 'worker'
    """
    setup_logging(verbose=verbose)

    apis, workers = discover_objects(files)

    try:
        for w in workers:
            w.initialize(redis_url)
    except ValueError as e:
        error_panel(str(e), title="Configuration error")
        raise typer.Exit(1)

    apis, workers = filter_components(apis, workers, only)

    print_services_panel(
        apis,
        workers,
        title="conduit",
        worker_line_fn=lambda w: worker_lines(w, redis_url=w.resolved_redis_url),
    )

    try:
        asyncio.run(run_services(apis, workers))
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl+C
    finally:
        nl()
