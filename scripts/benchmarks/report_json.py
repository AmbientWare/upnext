from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .metrics import sample_summary
from .models import SCHEMA_VERSION, BenchmarkResult, FrameworkSummary, MatrixRunRecord


def summarize_framework_runs(
    *,
    framework: str,
    workload: str,
    requested_runs: int,
    runs: list[BenchmarkResult],
) -> FrameworkSummary:
    ok_runs = [run for run in runs if run.status == "ok"]
    jps_summary = sample_summary([run.jobs_per_second for run in ok_runs])
    total_summary = sample_summary([run.total_seconds for run in ok_runs])
    enqueue_p95_summary = sample_summary([run.p95_enqueue_ms for run in ok_runs])
    queue_wait_p95_summary = sample_summary([run.p95_queue_wait_ms for run in ok_runs])
    enqueue_max_summary = sample_summary([run.max_enqueue_ms for run in ok_runs])
    queue_wait_max_summary = sample_summary([run.max_queue_wait_ms for run in ok_runs])

    return FrameworkSummary(
        framework=framework,
        workload=workload,
        requested_runs=requested_runs,
        ok_runs=len(ok_runs),
        non_ok_count=len(runs) - len(ok_runs),
        median_jobs_per_second=jps_summary["median"],
        mean_jobs_per_second=jps_summary["mean"],
        stdev_jobs_per_second=jps_summary["stdev"],
        median_total_seconds=total_summary["median"],
        median_p95_enqueue_ms=enqueue_p95_summary["median"],
        median_p95_queue_wait_ms=queue_wait_p95_summary["median"],
        median_max_enqueue_ms=enqueue_max_summary["median"],
        median_max_queue_wait_ms=queue_wait_max_summary["median"],
    )


def matrix_json_payload(
    *,
    config: dict[str, Any],
    warmups: list[MatrixRunRecord],
    runs: list[MatrixRunRecord],
    summaries: list[FrameworkSummary],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "benchmark-matrix",
        "config": config,
        "warmups": [record.to_dict() for record in warmups],
        "runs": [record.to_dict() for record in runs],
        "summaries": [asdict(summary) for summary in summaries],
    }
