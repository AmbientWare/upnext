"""Runtime orchestration for running multiple services together."""

import asyncio
import contextlib
import logging
import os
import signal
import sys
import time

from conduit.sdk.api import Api
from conduit.sdk.worker import Worker

logger = logging.getLogger(__name__)

# Default shutdown timeouts
DEFAULT_WORKER_TIMEOUT = 3.0  # Time for job processor to finish active jobs
DEFAULT_API_TIMEOUT = 1.5  # Time for uvicorn to finish requests

# Minimum time between signals to count as intentional second press (not duplicate delivery)
_SIGNAL_DEBOUNCE_SECONDS = 0.5


async def run_services(
    apis: list[Api],
    workers: list[Worker],
    *,
    worker_timeout: float = DEFAULT_WORKER_TIMEOUT,
    api_timeout: float = DEFAULT_API_TIMEOUT,
) -> None:
    """Start all APIs and Workers, wait for shutdown signal, then stop gracefully.

    Args:
        apis: List of Api instances to run.
        workers: List of Worker instances to run.
        worker_timeout: Seconds to wait for workers to finish active jobs before force-stopping (default 3.0).
        api_timeout: Seconds to wait for APIs to finish requests before force-stopping (default 1.5).

    Signal handling:
    - First SIGINT/SIGTERM: Graceful shutdown (stop services, wait for completion)
    - Second SIGINT/SIGTERM (after 0.5s): Force exit immediately
    """
    stop_event = asyncio.Event()
    shutting_down: bool = False
    last_signal_time: float = 0.0

    def handle_signal() -> None:
        nonlocal shutting_down, last_signal_time
        now = time.monotonic()

        if shutting_down:
            # Check if this is a duplicate signal delivery (< 0.5s) or intentional second press
            if now - last_signal_time < _SIGNAL_DEBOUNCE_SECONDS:
                # Ignore duplicate signal delivery from single Ctrl+C
                return
            # Intentional second signal - force exit immediately
            logger.warning("Received second interrupt signal, forcing immediate exit")
            sys.stderr.write("\nForced exit\n")
            sys.stderr.flush()
            os._exit(1)

        last_signal_time = now
        shutting_down = True
        sys.stderr.write("\nShutting down... (press Ctrl+C again to force)\n")
        sys.stderr.flush()
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    # Disable signal handling in components (we handle it at this level)
    for api in apis:
        api.handle_signals = False
    for worker in workers:
        worker.handle_signals = False

    # Start all services
    tasks: list[asyncio.Task[None]] = []
    for api in apis:
        tasks.append(asyncio.create_task(api.start()))
    for worker in workers:
        tasks.append(asyncio.create_task(worker.start()))

    # Wait for shutdown signal
    await stop_event.wait()

    # --- Graceful shutdown ---

    # Signal APIs to stop (non-blocking)
    for api in apis:
        api.stop()

    # Stop workers (waits for graceful shutdown)
    for worker in workers:
        try:
            await worker.stop(timeout=worker_timeout)
        except Exception:
            logger.debug(
                f"Exception during worker '{worker.name}' shutdown", exc_info=True
            )

    # Wait for API tasks to finish
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=api_timeout)
        for task in pending:
            task.cancel()
        if pending:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*pending, return_exceptions=True)

    # --- Cleanup ---

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.remove_signal_handler(sig)

    # Remove rich handlers to prevent errors during Python shutdown
    for handler in logging.root.handlers[:]:
        if "rich" in handler.__class__.__module__:
            logging.root.removeHandler(handler)

    logging.shutdown()
