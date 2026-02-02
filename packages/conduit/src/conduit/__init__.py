"""Conduit - Background job processing framework."""

import asyncio

from conduit.engine import run_services
from conduit.sdk import Api, Context, Worker, get_current_context
from conduit.types import BackendType, SyncExecutor

__all__ = [
    "Api",
    "Context",
    "Worker",
    "BackendType",
    "SyncExecutor",
    "run",
    "get_current_context",
]

__version__ = "0.1.0"


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
        import conduit

        api = conduit.Api("my-api")
        worker = conduit.Worker("my-worker")

        conduit.run(api, worker)

        # With custom timeouts (e.g., for long-running jobs):
        conduit.run(api, worker, worker_timeout=30.0)
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
