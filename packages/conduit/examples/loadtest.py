"""
Load test for measuring Conduit worker throughput.

Usage:
    # Terminal 1: Start the worker
    conduit run examples/loadtest.py

    # Terminal 2: Run the load test
    python examples/loadtest.py <task> <num_jobs>

Tasks:
    noop        - Minimal task, measures pure overhead
    light_cpu   - Light CPU work (sum of range)
    io_bound    - Simulated I/O (10ms async sleep)
    all         - Run all tasks and show comparison table

Examples:
    python examples/loadtest.py noop 10000
    python examples/loadtest.py light_cpu 5000
    python examples/loadtest.py io_bound 1000 --json
    python examples/loadtest.py all 5000          # Compare all task types

Docker Compose (with profile):
    docker compose --profile loadtest up
    docker compose --profile loadtest run loadtest-client all 5000
"""

import argparse
import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import conduit
from conduit.config import get_settings
from conduit.types import BackendType

if TYPE_CHECKING:
    from conduit.sdk.worker import TaskHandle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Worker definition (used by: conduit run examples/loadtest.py)
# ---------------------------------------------------------------------------

WORKER_CONCURRENCY = 200

worker = conduit.Worker(
    "loadtest",
    concurrency=WORKER_CONCURRENCY,
    backend=BackendType.REDIS,
)

VALID_TASKS = ["noop", "light_cpu", "io_bound", "all"]


@worker.task()
async def noop() -> None:
    """Minimal task - measures pure queue/execution overhead."""
    pass


@worker.task()
async def light_cpu() -> int:
    """Light CPU work - small computation."""
    logger.info("light_cpu task started")
    return sum(range(1000))


@worker.task()
async def io_bound() -> str:
    """Simulated I/O - 10ms async sleep."""
    await asyncio.sleep(0.01)
    return "done"


# Task handle lookup
TASK_HANDLES: dict[str, "TaskHandle"] = {
    "noop": noop,
    "light_cpu": light_cpu,
    "io_bound": io_bound,
}


# ---------------------------------------------------------------------------
# Load test runner (used by: python examples/loadtest.py)
# ---------------------------------------------------------------------------


@dataclass
class LoadTestResult:
    """Results from a load test run."""

    task: str
    num_jobs: int
    worker_concurrency: int
    submit_time_sec: float
    submit_rate: float
    total_time_sec: float
    throughput: float

    def print_summary(self) -> None:
        """Print human-readable summary."""
        print()
        print("=" * 50)
        print(f"  Task:        {self.task}")
        print(f"  Jobs:        {self.num_jobs:,}")
        print(f"  Concurrency: {self.worker_concurrency}")
        print(
            f"  Submit:      {self.submit_time_sec:.2f}s ({self.submit_rate:,.0f}/sec)"
        )
        print(f"  Total:       {self.total_time_sec:.2f}s")
        print(f"  Throughput:  {self.throughput:,.0f} jobs/sec")
        print("=" * 50)
        print()

    def to_json(self) -> str:
        """Return JSON representation."""
        return json.dumps(asdict(self), indent=2)


def print_comparison_table(results: list["LoadTestResult"]) -> None:
    """Print a comparison table of multiple load test results."""
    print()
    print("=" * 70)
    print("  LOAD TEST COMPARISON")
    print("=" * 70)
    print()
    print(
        f"  {'Task':<12} {'Jobs':>8} {'Submit/s':>10} {'Total(s)':>10} {'Throughput':>12}"
    )
    print(f"  {'-' * 12} {'-' * 8} {'-' * 10} {'-' * 10} {'-' * 12}")
    for r in results:
        print(
            f"  {r.task:<12} {r.num_jobs:>8,} {r.submit_rate:>10,.0f} "
            f"{r.total_time_sec:>10.2f} {r.throughput:>10,.0f}/s"
        )
    print()
    print(f"  Worker concurrency: {results[0].worker_concurrency}")
    print("=" * 70)
    print()


async def submit_jobs(
    task_handle: "TaskHandle", num_jobs: int, quiet: bool = False
) -> float:
    """Submit all jobs concurrently in batches. Returns elapsed time."""
    start = time.perf_counter()
    batch_size = 100

    for batch_start in range(0, num_jobs, batch_size):
        batch_end = min(batch_start + batch_size, num_jobs)
        batch_count = batch_end - batch_start

        # Submit batch concurrently using task handle
        coros = [task_handle.submit() for _ in range(batch_count)]
        await asyncio.gather(*coros)

        # Progress every 1000 jobs
        if not quiet and (batch_end % 1000 == 0 or batch_end == num_jobs):
            elapsed = time.perf_counter() - start
            rate = batch_end / elapsed if elapsed > 0 else 0
            print(f"  {batch_end:,}/{num_jobs:,} ({rate:,.0f}/sec)")

    return time.perf_counter() - start


async def get_loadtest_stats() -> dict[str, int]:
    """Get stats for only the loadtest functions (noop, light_cpu, io_bound)."""
    from conduit.engine.queue import RedisQueue

    settings = get_settings()
    assert settings.redis_url is not None
    queue = RedisQueue(redis_url=settings.redis_url)

    try:
        total_queued = 0
        total_active = 0
        for func in ["noop", "light_cpu", "io_bound"]:
            stats = await queue.get_queue_stats(func)
            total_queued += stats.queued
            total_active += stats.active
        return {"queued": total_queued, "active": total_active}
    finally:
        await queue.close()


async def wait_for_completion(quiet: bool = False) -> None:
    """Wait for loadtest jobs to be fully processed."""
    last_remaining = -1
    stall_count = 0

    while True:
        stats = await get_loadtest_stats()
        queued = stats.get("queued", 0)
        active = stats.get("active", 0)
        remaining = queued + active

        if remaining == 0:
            break

        if remaining != last_remaining:
            if not quiet:
                print(
                    f"  Remaining: {remaining:,} (queued={queued:,}, active={active})"
                )
            last_remaining = remaining
            stall_count = 0
        else:
            stall_count += 1
            if stall_count > 20:  # 10 seconds no progress
                if not quiet:
                    print("  Warning: No progress. Is the worker running?")
                stall_count = 0

        await asyncio.sleep(0.5)


async def drain_queue(quiet: bool = False) -> None:
    """Wait for any existing loadtest jobs to be processed."""
    while True:
        stats = await get_loadtest_stats()
        remaining = stats.get("queued", 0) + stats.get("active", 0)

        if remaining == 0:
            break

        if not quiet:
            print(f"  Draining: {remaining:,} remaining...")
        await asyncio.sleep(0.5)


async def run_loadtest(task: str, num_jobs: int, quiet: bool = False) -> LoadTestResult:
    """Run the load test and return results."""
    settings = get_settings()

    if worker.backend != BackendType.REDIS:
        raise SystemExit(
            "Error: Load test requires Redis. Set backend=BackendType.REDIS on the worker."
        )

    # Initialize the worker (connects to Redis, sets up task handles)
    await worker._initialize()

    if not quiet:
        print(f"Connected to Redis: {settings.redis_url}")

    # Drain any leftover loadtest jobs from previous runs
    stats = await get_loadtest_stats()

    if stats.get("queued", 0) + stats.get("active", 0) > 0:
        if not quiet:
            print("Draining leftover jobs from previous run...")
        await drain_queue(quiet=quiet)

    # Get the task handle
    task_handle = TASK_HANDLES.get(task)
    if not task_handle:
        raise SystemExit(f"Unknown task: {task}")

    if not quiet:
        print(f"\nLoad test: {task} x {num_jobs:,}\n")
        print("Submitting...")

    # Submit phase
    total_start = time.perf_counter()
    submit_time = await submit_jobs(task_handle, num_jobs, quiet=quiet)
    submit_rate = num_jobs / submit_time

    if not quiet:
        print(f"\nSubmitted in {submit_time:.2f}s ({submit_rate:,.0f}/sec)\n")
        print("Processing...")

    # Wait phase
    await wait_for_completion(quiet=quiet)

    total_time = time.perf_counter() - total_start
    throughput = num_jobs / total_time

    return LoadTestResult(
        task=task,
        num_jobs=num_jobs,
        worker_concurrency=WORKER_CONCURRENCY,
        submit_time_sec=round(submit_time, 3),
        submit_rate=round(submit_rate, 1),
        total_time_sec=round(total_time, 3),
        throughput=round(throughput, 1),
    )


async def run_all_loadtests(num_jobs: int, quiet: bool = False) -> list[LoadTestResult]:
    """Run all task types and return results."""
    tasks_to_run = ["noop", "light_cpu", "io_bound"]
    results = []

    for task in tasks_to_run:
        if not quiet:
            print(f"\n{'=' * 50}")
            print(f"  Running: {task}")
            print(f"{'=' * 50}")
        result = await run_loadtest(task, num_jobs, quiet=quiet)
        results.append(result)
        if not quiet:
            print(f"  Completed: {result.throughput:,.0f} jobs/sec")

    return results


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Load test for Conduit worker throughput",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/loadtest.py noop 10000
  python examples/loadtest.py light_cpu 5000
  python examples/loadtest.py io_bound 1000 --json
  python examples/loadtest.py all 5000          # Run all tasks with 5000 jobs each
        """,
    )
    parser.add_argument(
        "task", choices=VALID_TASKS, help="Task to benchmark ('all' runs all tasks)"
    )
    parser.add_argument(
        "num_jobs", type=int, help="Number of jobs to submit (per task if 'all')"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON (quiet mode)"
    )

    args = parser.parse_args()

    if args.task == "all":
        results = asyncio.run(run_all_loadtests(args.num_jobs, quiet=args.json))
        if args.json:
            print(json.dumps([asdict(r) for r in results], indent=2))
        else:
            print_comparison_table(results)
    else:
        result = asyncio.run(run_loadtest(args.task, args.num_jobs, quiet=args.json))
        if args.json:
            print(result.to_json())
        else:
            result.print_summary()


if __name__ == "__main__":
    main()
