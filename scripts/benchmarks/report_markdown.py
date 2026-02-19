from __future__ import annotations

from typing import Any


def _fmt_float(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def _fmt_intlike(value: float) -> str:
    return f"{value:,.0f}"


def _tail_ratio(max_value: float, p95_value: float) -> float:
    if p95_value <= 0:
        return 0.0
    return max_value / p95_value


def _config_header(config: dict[str, Any]) -> str:
    workload = str(config.get("workload", "unknown"))
    jobs = int(config.get("jobs", 0) or 0)
    concurrency = int(config.get("concurrency", 0) or 0)
    producers = int(config.get("producer_concurrency", 0) or 0)
    repeats = int(config.get("repeats", 0) or 0)
    warmups = int(config.get("warmups", 0) or 0)

    line = (
        f"{workload} · jobs {jobs:,} · concurrency {concurrency} · "
        f"producers {producers} · {repeats} repeats · {warmups} warmups"
    )
    if workload == "sustained":
        duration = float(config.get("duration_seconds", 0.0) or 0.0)
        arrival = float(config.get("arrival_rate", 0.0) or 0.0)
        line += f" · duration {duration:.1f}s · arrival {arrival:.1f} jobs/s"
    return line


def build_markdown_report(payloads: list[dict[str, Any]]) -> str:
    if not payloads:
        return "> No benchmark result payloads found.\n"

    lines: list[str] = ["## Benchmark Results", ""]
    for payload in payloads:
        config = payload.get("config", {})
        lines.append(f"### {_config_header(config)}")
        lines.append("")
        lines.append(
            "| Framework | Jobs/s | Total (s) | p95 enqueue (ms) | p95 queue wait (ms) | Tail ratio (max/p95 enqueue) | Runs |"
        )
        lines.append("|:--|--:|--:|--:|--:|--:|--:|")

        raw_summaries = payload.get("summaries", [])
        summaries = [row for row in raw_summaries if isinstance(row, dict)]
        summaries.sort(
            key=lambda row: float(row.get("median_jobs_per_second", 0.0)),
            reverse=True,
        )

        for summary in summaries:
            framework = str(summary.get("framework", "unknown"))
            jps = float(summary.get("median_jobs_per_second", 0.0))
            stdev = float(summary.get("stdev_jobs_per_second", 0.0))
            total = float(summary.get("median_total_seconds", 0.0))
            enqueue_p95 = float(summary.get("median_p95_enqueue_ms", 0.0))
            queue_wait_p95 = float(summary.get("median_p95_queue_wait_ms", 0.0))
            enqueue_max = float(summary.get("median_max_enqueue_ms", 0.0))
            tail_ratio = _tail_ratio(enqueue_max, enqueue_p95)
            ok_runs = int(summary.get("ok_runs", 0))
            requested_runs = int(summary.get("requested_runs", 0))

            jps_cell = _fmt_intlike(jps)
            if stdev > 0:
                jps_cell += f" ±{_fmt_intlike(stdev)}"

            lines.append(
                f"| {framework} | {jps_cell} | {_fmt_float(total)} | "
                f"{_fmt_float(enqueue_p95)} | {_fmt_float(queue_wait_p95)} | "
                f"{_fmt_float(tail_ratio, 2)} | {ok_runs}/{requested_runs} |"
            )
        lines.append("")

    return "\n".join(lines)
