"""Read benchmark JSON artifacts and output a combined GitHub-flavored markdown report.

Usage (from the workflow summary job):
    python scripts/benchmarks/summarize.py results/

Only uses stdlib so no venv or package install is needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _extract_json(text: str) -> dict | None:
    """Find and parse the first top-level JSON object in *text*."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _fmt(value: float, decimals: int = 3) -> str:
    return f"{value:.{decimals}f}"


def _fmt_jps(value: float, stdev: float) -> str:
    s = f"{value:,.0f}"
    if stdev:
        s += f" ±{stdev:,.0f}"
    return s


def _build_markdown(results_dir: Path) -> str:
    # Collect (profile, summary_dict, config_dict) from each artifact.
    entries: list[tuple[str, dict, dict]] = []

    for artifact_dir in sorted(results_dir.iterdir()):
        output_file = artifact_dir / "benchmark-output.txt"
        if not output_file.is_file():
            continue
        data = _extract_json(output_file.read_text())
        if not data:
            continue

        config = data.get("config", {})
        profile = config.get("profile", "unknown")
        for summary in data.get("summaries", []):
            entries.append((profile, summary, config))

    if not entries:
        return "> No benchmark results found.\n"

    # Group by profile.  Show throughput before durability.
    profile_order = ["throughput", "durability"]
    profiles: dict[str, list[tuple[dict, dict]]] = {}
    for profile, summary, config in entries:
        profiles.setdefault(profile, []).append((summary, config))
    profiles = {
        k: profiles[k]
        for k in profile_order
        if k in profiles
    } | {
        k: v
        for k, v in profiles.items()
        if k not in profile_order
    }

    # Use config from first entry for the header.
    first_config = entries[0][2]
    lines: list[str] = []
    lines.append("## Benchmark Results")
    lines.append("")
    lines.append(
        f"> **{first_config.get('jobs', '?'):,} jobs** · "
        f"concurrency {first_config.get('concurrency', '?')} · "
        f"{first_config.get('payload_bytes', '?')} B payload · "
        f"{first_config.get('repeats', '?')} repeats · "
        f"{first_config.get('warmups', '?')} warmups"
    )
    lines.append("")

    for profile, items in profiles.items():
        lines.append(f"### {profile}")
        lines.append("")
        lines.append(
            "| Framework | Jobs/s | Total (s) "
            "| p50 (ms) | p95 (ms) | p99 (ms) | max (ms) | Runs |"
        )
        lines.append(
            "|:----------|-------:|----------:"
            "|---------:|---------:|---------:|---------:|-----:|"
        )

        # Sort by jobs/s descending.
        items.sort(key=lambda x: x[0].get("median_jobs_per_second", 0), reverse=True)
        best_jps = items[0][0].get("median_jobs_per_second", 0) if items else 0

        for summary, _cfg in items:
            fw = summary.get("framework", "?")
            jps = summary.get("median_jobs_per_second", 0)
            stdev = summary.get("stdev_jobs_per_second", 0)
            total = summary.get("median_total_seconds", 0)
            p50 = summary.get("median_p50_enqueue_ms", 0)
            p95 = summary.get("median_p95_enqueue_ms", 0)
            p99 = summary.get("median_p99_enqueue_ms", 0)
            mx = summary.get("median_max_enqueue_ms", 0)
            ok = summary.get("ok_runs", 0)
            req = summary.get("requested_runs", 0)

            name = f"**{fw}**" if jps == best_jps and len(items) > 1 else fw

            lines.append(
                f"| {name} "
                f"| {_fmt_jps(jps, stdev)} "
                f"| {_fmt(total)} "
                f"| {_fmt(p50)} "
                f"| {_fmt(p95)} "
                f"| {_fmt(p99)} "
                f"| {_fmt(mx)} "
                f"| {ok}/{req} |"
            )

        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python scripts/benchmarks/summarize.py <results-dir>", file=sys.stderr)
        return 1

    results_dir = Path(args[0])
    if not results_dir.is_dir():
        print(f"Not a directory: {results_dir}", file=sys.stderr)
        return 1

    print(_build_markdown(results_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
