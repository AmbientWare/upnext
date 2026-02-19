from __future__ import annotations

from typing import Any

from .models import BenchmarkResult, MatrixRunRecord


def _fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def print_single_result(result: BenchmarkResult) -> None:
    print(
        " | ".join(
            [
                f"framework={result.framework}",
                f"workload={result.workload}",
                f"status={result.status}",
                f"jobs/s={result.jobs_per_second:,.0f}",
                f"total_s={_fmt(result.total_seconds)}",
                f"p95_enqueue_ms={_fmt(result.p95_enqueue_ms)}",
                f"p95_queue_wait_ms={_fmt(result.p95_queue_wait_ms)}",
                f"queue_wait_samples={result.queue_wait_samples}",
            ]
        )
    )


def print_matrix_report(
    *,
    config: dict[str, Any],
    summaries: list[dict[str, Any]],
    runs: list[MatrixRunRecord],
    show_runs: bool,
) -> None:
    print()
    print(
        "Benchmark Matrix "
        f"workload={config.get('workload')}"
    )
    print(
        "config: "
        f"jobs={config.get('jobs')} concurrency={config.get('concurrency')} "
        f"producers={config.get('producer_concurrency')} repeats={config.get('repeats')} "
        f"warmups={config.get('warmups')} "
        f"duration_s={config.get('duration_seconds')} "
        f"arrival_rate={config.get('arrival_rate')}"
    )
    print()
    print(
        "framework            jobs/s      total(s)   p95 enqueue(ms)   "
        "p95 queue-wait(ms)   runs"
    )
    print("-" * 88)

    sorted_summaries = sorted(
        summaries,
        key=lambda row: float(row.get("median_jobs_per_second", 0.0)),
        reverse=True,
    )
    for row in sorted_summaries:
        framework = str(row.get("framework", "?"))
        jps = float(row.get("median_jobs_per_second", 0.0))
        total = float(row.get("median_total_seconds", 0.0))
        p95_enqueue = float(row.get("median_p95_enqueue_ms", 0.0))
        p95_queue_wait = float(row.get("median_p95_queue_wait_ms", 0.0))
        ok_runs = int(row.get("ok_runs", 0))
        requested_runs = int(row.get("requested_runs", 0))
        print(
            f"{framework:<20} {_fmt(jps, 0):>10} { _fmt(total):>12} "
            f"{_fmt(p95_enqueue):>17} {_fmt(p95_queue_wait):>20} "
            f"{ok_runs}/{requested_runs:>5}"
        )

    if show_runs:
        print("\nper-run detail:")
        print("phase    idx  framework            status   jobs/s      total(s)")
        print("-" * 72)
        for record in runs:
            result = record.result
            print(
                f"{record.phase:<8} {record.run_index:>3}  {record.framework:<20} "
                f"{result.status:<7} {_fmt(result.jobs_per_second, 0):>10} "
                f"{_fmt(result.total_seconds):>12}"
            )
    print()
