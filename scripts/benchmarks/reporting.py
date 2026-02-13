from __future__ import annotations

import statistics
from dataclasses import asdict
from typing import Any

from .models import BenchmarkResult, FrameworkSummary


def summarize_framework_runs(
    framework: str,
    runs: list[BenchmarkResult],
    *,
    requested_runs: int,
) -> FrameworkSummary:
    ok = [run for run in runs if run.status == "ok"]
    jobs_per_second = [run.jobs_per_second for run in ok]
    total_seconds = [run.total_seconds for run in ok]
    p95_enqueue_ms = [run.p95_enqueue_ms for run in ok]

    if not ok:
        return FrameworkSummary(
            framework=framework,
            requested_runs=requested_runs,
            ok_runs=0,
            median_jobs_per_second=0.0,
            mean_jobs_per_second=0.0,
            stdev_jobs_per_second=0.0,
            median_total_seconds=0.0,
            median_p95_enqueue_ms=0.0,
            non_ok_count=len(runs),
        )

    stdev = (
        statistics.pstdev(jobs_per_second)
        if len(jobs_per_second) > 1
        else 0.0
    )

    return FrameworkSummary(
        framework=framework,
        requested_runs=requested_runs,
        ok_runs=len(ok),
        median_jobs_per_second=statistics.median(jobs_per_second),
        mean_jobs_per_second=statistics.mean(jobs_per_second),
        stdev_jobs_per_second=stdev,
        median_total_seconds=statistics.median(total_seconds),
        median_p95_enqueue_ms=statistics.median(p95_enqueue_ms),
        non_ok_count=len(runs) - len(ok),
    )


def print_summary_table(summaries: list[FrameworkSummary]) -> None:
    headers = [
        "framework",
        "ok/req",
        "median_jobs/s",
        "mean_jobs/s",
        "stdev_jobs/s",
        "median_total_s",
        "median_p95_enqueue_ms",
        "non_ok",
    ]
    rows = [headers]

    for summary in summaries:
        rows.append(
            [
                summary.framework,
                f"{summary.ok_runs}/{summary.requested_runs}",
                f"{summary.median_jobs_per_second:.1f}",
                f"{summary.mean_jobs_per_second:.1f}",
                f"{summary.stdev_jobs_per_second:.1f}",
                f"{summary.median_total_seconds:.3f}",
                f"{summary.median_p95_enqueue_ms:.3f}",
                str(summary.non_ok_count),
            ]
        )

    widths = [max(len(row[idx]) for row in rows) for idx in range(len(headers))]
    for idx, row in enumerate(rows):
        line = " | ".join(item.ljust(widths[col]) for col, item in enumerate(row))
        print(line)
        if idx == 0:
            print("-+-".join("-" * w for w in widths))


def print_raw_runs(framework: str, runs: list[BenchmarkResult]) -> None:
    print(f"\n{framework} runs:")
    headers = [
        "run",
        "status",
        "jobs/s",
        "enqueue_s",
        "drain_s",
        "total_s",
        "p95_enqueue_ms",
    ]
    rows = [headers]
    for idx, run in enumerate(runs, start=1):
        rows.append(
            [
                str(idx),
                run.status,
                f"{run.jobs_per_second:.1f}",
                f"{run.enqueue_seconds:.3f}",
                f"{run.drain_seconds:.3f}",
                f"{run.total_seconds:.3f}",
                f"{run.p95_enqueue_ms:.3f}",
            ]
        )

    widths = [max(len(row[idx]) for row in rows) for idx in range(len(headers))]
    for idx, row in enumerate(rows):
        line = " | ".join(item.ljust(widths[col]) for col, item in enumerate(row))
        print(line)
        if idx == 0:
            print("-+-".join("-" * w for w in widths))


def json_payload(
    *,
    config: dict[str, Any],
    runs_by_framework: dict[str, list[BenchmarkResult]],
    summaries: list[FrameworkSummary],
) -> dict[str, Any]:
    return {
        "config": config,
        "summaries": [asdict(summary) for summary in summaries],
        "runs": {
            framework: [asdict(run) for run in runs]
            for framework, runs in runs_by_framework.items()
        },
    }
