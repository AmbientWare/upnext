"""Best-effort component discovery for `upnext init`."""

from __future__ import annotations

from pathlib import Path

import typer

from upnext.cli._console import warning
from upnext.cli._loader import discover_objects


def discover_component_names(
    entrypoint_path: Path,
) -> tuple[list[str], list[str], bool]:
    try:
        apis, workers = discover_objects([str(entrypoint_path)])
    except typer.Exit as exc:
        warning(
            "Could not validate Api/Worker discovery locally. "
            f"Config will still be written ({exc.exit_code})."
        )
        return [], [], False
    except Exception as exc:
        warning(
            "Could not validate Api/Worker discovery locally. "
            f"Config will still be written ({exc})."
        )
        return [], [], False

    api_names = [api.name for api in apis]
    worker_names = [worker.name for worker in workers]
    if not api_names and not worker_names:
        warning(
            "No Api or Worker objects were discovered in the entrypoint. "
            "Config will still be written."
        )
    return api_names, worker_names, True
