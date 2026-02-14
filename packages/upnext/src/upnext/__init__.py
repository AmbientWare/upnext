"""UpNext - Background job processing framework."""

import asyncio

from shared._version import __version__
from shared.artifacts import ArtifactType

from upnext.engine import run_services
from upnext.sdk import (
    Api,
    Context,
    TaskTimeoutError,
    Worker,
    create_artifact,
    create_artifact_sync,
    get_current_context,
)
from upnext.types import SyncExecutor

__all__ = [
    "Api",
    "ArtifactType",
    "Context",
    "TaskTimeoutError",
    "Worker",
    "SyncExecutor",
    "__version__",
    "create_artifact",
    "create_artifact_sync",
    "get_current_context",
    "run",
]


def run(
    *components: Api | Worker,
    worker_timeout: float = 3.0,
    api_timeout: float = 1.5,
) -> None:
    """Run one or more Api and/or Worker instances.

    Handles signal coordination so Ctrl+C gracefully stops all components.

    Args:
        *components: Api and/or Worker instances to run.
        worker_timeout: Seconds to wait for workers to finish active jobs before force-stopping (default 3.0).
        api_timeout: Seconds to wait for APIs to finish requests before force-stopping (default 1.5).

    Example:
        import upnext

        api = upnext.Api("my-api")
        worker = upnext.Worker("my-worker")

        upnext.run(api, worker)

        # With custom timeouts (e.g., for long-running jobs):
        upnext.run(api, worker, worker_timeout=30.0)
    """
    apis = [c for c in components if isinstance(c, Api)]
    workers = [c for c in components if isinstance(c, Worker)]

    try:
        asyncio.run(
            run_services(
                apis, workers, worker_timeout=worker_timeout, api_timeout=api_timeout
            )
        )
    except KeyboardInterrupt:
        pass
