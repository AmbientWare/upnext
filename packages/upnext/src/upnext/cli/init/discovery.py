"""Best-effort component discovery for `upnext init`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from upnext.cli._console import warning
from upnext.cli._loader import discover_objects


@dataclass(frozen=True)
class DiscoveredApi:
    name: str
    port: int


def discover_components(
    entrypoint_path: Path,
) -> tuple[list[DiscoveredApi], list[str], bool]:
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

    discovered_apis = [DiscoveredApi(name=api.name, port=api.port) for api in apis]
    worker_names = [worker.name for worker in workers]
    if not discovered_apis and not worker_names:
        warning(
            "No Api or Worker objects were discovered in the entrypoint. "
            "Config will still be written."
        )
    return discovered_apis, worker_names, True
