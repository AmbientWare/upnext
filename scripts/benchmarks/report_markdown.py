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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_frameworks(value: Any) -> str:
    if not isinstance(value, list):
        return "-"
    items = [str(item).strip() for item in value if str(item).strip()]
    return ", ".join(items) if items else "-"


def _config_header(config: dict[str, Any]) -> str:
    workload = str(config.get("workload", "unknown"))
    profile = str(config.get("profile", "base"))
    jobs = _as_int(config.get("jobs", 0))
    concurrency = _as_int(config.get("concurrency", 0))
    producers = _as_int(config.get("producer_concurrency", 0))
    repeats = _as_int(config.get("repeats", 0))
    warmups = _as_int(config.get("warmups", 0))

    line = (
        f"{workload} · profile {profile} · jobs {jobs:,} · concurrency {concurrency} · "
        f"producers {producers} · {repeats} repeats · {warmups} warmups"
    )
    if workload == "sustained":
        duration = _as_float(config.get("duration_seconds", 0.0))
        arrival = _as_float(config.get("arrival_rate", 0.0))
        line += f" · duration {duration:.1f}s · arrival {arrival:.1f} jobs/s"
    return line


def build_markdown_report(payloads: list[dict[str, Any]]) -> str:
    if not payloads:
        return "> No benchmark result payloads found.\n"

    lines: list[str] = ["## Benchmark Results", ""]
    lines.append("### Settings Summary")
    lines.append("")
    lines.append(
        "| Workload | Profile | Frameworks | Jobs | Concurrency | Producers | Repeats | Warmups | Duration (s) | Arrival (jobs/s) | Payload (bytes) | Prefetch | Queue Wait Sample | Queue Wait Max | Seed |"
    )
    lines.append("|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")

    for payload in payloads:
        config = payload.get("config")
        if not isinstance(config, dict):
            continue
        lines.append(
            f"| {str(config.get('workload', 'unknown'))} "
            f"| {str(config.get('profile', 'base'))} "
            f"| {_as_frameworks(config.get('frameworks'))} "
            f"| {_as_int(config.get('jobs', 0)):,} "
            f"| {_as_int(config.get('concurrency', 0))} "
            f"| {_as_int(config.get('producer_concurrency', 0))} "
            f"| {_as_int(config.get('repeats', 0))} "
            f"| {_as_int(config.get('warmups', 0))} "
            f"| {_fmt_float(_as_float(config.get('duration_seconds', 0.0)), 1)} "
            f"| {_fmt_float(_as_float(config.get('arrival_rate', 0.0)), 1)} "
            f"| {_as_int(config.get('payload_bytes', 0))} "
            f"| {_as_int(config.get('consumer_prefetch', 0))} "
            f"| {_fmt_float(_as_float(config.get('queue_wait_sample_rate', 0.0)), 2)} "
            f"| {_as_int(config.get('queue_wait_max_samples', 0))} "
            f"| {_as_int(config.get('seed', 0))} |"
        )
    lines.append("")

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
