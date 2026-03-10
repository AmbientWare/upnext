"""Run command for UpNext services."""

import asyncio
import logging
import os
import signal
import subprocess
import sys

import typer

from upnext.cli._console import console, error_panel, info, nl, setup_logging, success, warning
from upnext.cli._display import (
    filter_components,
    print_services_panel,
    run_services,
    worker_lines,
)
from upnext.cli._loader import discover_objects

logger = logging.getLogger(__name__)


def _dev_server_popen_kwargs() -> dict[str, object]:
    """Return cross-platform Popen kwargs for dev servers."""
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags} if creationflags else {}
    return {"preexec_fn": os.setsid}


def _terminate_dev_server(proc: subprocess.Popen) -> None:
    """Terminate a dev server process without Unix-only APIs on Windows."""
    if os.name == "nt":
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            try:
                proc.send_signal(ctrl_break)
                return
            except OSError:
                pass
        proc.terminate()
        return
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)


def _kill_dev_server(proc: subprocess.Popen) -> None:
    """Force-kill a dev server process without Unix-only APIs on Windows."""
    if os.name == "nt":
        proc.kill()
        return
    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


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
    dev: bool = typer.Option(
        False,
        "--dev",
        help="Dev mode: start frontend dev servers (e.g. bun dev) instead of serving built assets",
    ),
    skip_build: bool = typer.Option(
        False,
        "--skip-build",
        help="Skip frontend build step (use when assets are already built, e.g. in Docker)",
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
        upnext run service.py                    # Run all (builds frontend first)
        upnext run service.py --dev              # Dev mode with frontend HMR
        upnext run service.py --skip-build       # Skip frontend build (Docker)
        upnext run service.py --redis-url redis://localhost:6379
        upnext run service.py -o api -o worker   # Run 'api' and 'worker'
    """
    setup_logging(verbose=verbose)

    all_apis, all_workers = discover_objects(files)

    # Initialize all workers so task/event handles have queue connections
    # even when filtered out by --only (APIs need to submit jobs)
    try:
        for w in all_workers:
            w.initialize(redis_url)
    except ValueError as e:
        error_panel(str(e), title="Configuration error")
        raise typer.Exit(1)

    # these are the components that will be run
    apis, workers = filter_components(all_apis, all_workers, only)

    # Collect static mounts with build/dev commands
    buildable_mounts = [
        mount
        for api in apis
        for mount in api.static_mounts
        if mount.build_command and mount.package_manager
    ]

    dev_processes: list[subprocess.Popen] = []

    if dev:
        # Dev mode: enable debug on all APIs + start frontend dev servers
        for api in apis:
            api.debug = True
        dev_processes = _start_dev_servers(buildable_mounts)
    elif not skip_build and buildable_mounts:
        # Prod mode: install deps + build frontend assets
        _build_static_assets(buildable_mounts)

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
        _stop_dev_servers(dev_processes)
        nl()


def _build_static_assets(mounts: list) -> None:
    """Install dependencies and run build commands for static mounts."""
    from upnext.sdk.api import StaticMount

    nl()
    console.print("  [bold]Building static assets[/bold]")

    for mount in mounts:
        mount: StaticMount
        cwd = os.path.abspath(mount.directory)

        if not os.path.isdir(cwd):
            warning(f"Skipping build — directory not found: {mount.directory}")
            continue

        # Install dependencies
        if mount.install_command:
            info(f"[dim]{mount.directory}[/dim] → {mount.install_command}")
            try:
                result = subprocess.run(
                    mount.install_command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except subprocess.TimeoutExpired:
                error_panel(f"Install timed out in {mount.directory}", title="Build error")
                raise typer.Exit(1)
            if result.returncode != 0:
                error_panel(
                    f"Install failed in {mount.directory}:\n{result.stderr.strip()}",
                    title="Build error",
                )
                raise typer.Exit(1)

        # Run build
        info(f"[dim]{mount.directory}[/dim] → {mount.build_command}")
        try:
            result = subprocess.run(
                mount.build_command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            error_panel(f"Build timed out in {mount.directory}", title="Build error")
            raise typer.Exit(1)
        if result.returncode != 0:
            error_panel(
                f"Build failed in {mount.directory}:\n{result.stderr.strip()}",
                title="Build error",
            )
            raise typer.Exit(1)

        success(f"Built {mount.directory}")

    nl()


def _start_dev_servers(mounts: list) -> list[subprocess.Popen]:
    """Start frontend dev servers as background processes."""
    from upnext.sdk.api import StaticMount

    processes: list[subprocess.Popen] = []

    if not mounts:
        return processes

    nl()
    console.print("  [bold]Starting dev servers[/bold]")

    for mount in mounts:
        mount: StaticMount
        if not mount.dev_command:
            continue

        cwd = os.path.abspath(mount.directory)
        if not os.path.isdir(cwd):
            warning(f"Skipping dev server — directory not found: {mount.directory}")
            continue

        info(f"[dim]{mount.directory}[/dim] → {mount.dev_command}")
        proc = subprocess.Popen(
            mount.dev_command,
            shell=True,
            cwd=cwd,
            stdout=sys.stdout,
            stderr=sys.stderr,
            **_dev_server_popen_kwargs(),
        )
        processes.append(proc)
        success(f"Dev server started for {mount.directory} (pid {proc.pid})")

    nl()
    return processes


def _stop_dev_servers(processes: list[subprocess.Popen]) -> None:
    """Gracefully stop dev server process groups."""
    for proc in processes:
        try:
            if proc.poll() is None:
                _terminate_dev_server(proc)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _kill_dev_server(proc)
        except OSError:
            pass
