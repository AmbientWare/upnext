from __future__ import annotations

import statistics
from dataclasses import asdict
from typing import Any

from rich.box import ROUNDED, SIMPLE_HEAD
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import BenchmarkResult, FrameworkSummary

console = Console(highlight=False)


def summarize_framework_runs(
    framework: str,
    runs: list[BenchmarkResult],
    *,
    requested_runs: int,
) -> FrameworkSummary:
    ok = [run for run in runs if run.status == "ok"]
    jobs_per_second = [run.jobs_per_second for run in ok]
    total_seconds = [run.total_seconds for run in ok]
    p50_enqueue_ms = [run.p50_enqueue_ms for run in ok]
    p95_enqueue_ms = [run.p95_enqueue_ms for run in ok]
    p99_enqueue_ms = [run.p99_enqueue_ms for run in ok]
    max_enqueue_ms = [run.max_enqueue_ms for run in ok]

    if not ok:
        return FrameworkSummary(
            framework=framework,
            requested_runs=requested_runs,
            ok_runs=0,
            median_jobs_per_second=0.0,
            mean_jobs_per_second=0.0,
            stdev_jobs_per_second=0.0,
            median_total_seconds=0.0,
            median_p50_enqueue_ms=0.0,
            median_p95_enqueue_ms=0.0,
            median_p99_enqueue_ms=0.0,
            median_max_enqueue_ms=0.0,
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
        median_p50_enqueue_ms=statistics.median(p50_enqueue_ms),
        median_p95_enqueue_ms=statistics.median(p95_enqueue_ms),
        median_p99_enqueue_ms=statistics.median(p99_enqueue_ms),
        median_max_enqueue_ms=statistics.median(max_enqueue_ms),
        non_ok_count=len(runs) - len(ok),
    )


# ---------------------------------------------------------------------------
# Rich output
# ---------------------------------------------------------------------------


def _config_panel(config: dict[str, Any]) -> Panel:
    """Build a Rich Panel showing benchmark configuration."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", min_width=14)
    grid.add_column(min_width=10)
    grid.add_column(style="dim", min_width=14)
    grid.add_column(min_width=10)

    grid.add_row(
        "Jobs",
        f"{config['jobs']:,}",
        "Payload",
        f"{config['payload_bytes']:,} B",
    )
    grid.add_row(
        "Concurrency",
        str(config["concurrency"]),
        "Producers",
        str(config["producer_concurrency"]),
    )
    grid.add_row(
        "Repeats",
        str(config["repeats"]),
        "Warmups",
        str(config["warmups"]),
    )

    return Panel(
        grid,
        title=f"[bold]Benchmark · {config['profile']}[/bold]",
        title_align="left",
        border_style="dim",
        box=ROUNDED,
        padding=(1, 2),
        expand=False,
    )


def _summary_table(summaries: list[FrameworkSummary]) -> Table:
    """Build a Rich Table for the framework summary."""
    best_jps = max(
        (s.median_jobs_per_second for s in summaries if s.ok_runs > 0),
        default=0.0,
    )

    table = Table(
        box=SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        padding=(0, 2),
        expand=False,
    )

    table.add_column("Framework", style="bold", no_wrap=True)
    table.add_column("Jobs/s", justify="right", no_wrap=True)
    table.add_column("Total (s)", justify="right", no_wrap=True)
    table.add_column("p50 (ms)", justify="right", no_wrap=True, header_style="dim")
    table.add_column("p95 (ms)", justify="right", no_wrap=True, header_style="dim")
    table.add_column("p99 (ms)", justify="right", no_wrap=True, header_style="dim")
    table.add_column("max (ms)", justify="right", no_wrap=True, header_style="dim")
    table.add_column("Runs", justify="right", no_wrap=True)

    for s in summaries:
        is_best = s.ok_runs > 0 and s.median_jobs_per_second == best_jps
        has_failures = s.non_ok_count > 0

        if has_failures:
            row_style = "dim"
        elif is_best and len(summaries) > 1:
            row_style = "green"
        else:
            row_style = ""

        stdev_note = f" ±{s.stdev_jobs_per_second:,.0f}" if s.stdev_jobs_per_second else ""

        table.add_row(
            s.framework,
            f"{s.median_jobs_per_second:,.0f}{stdev_note}",
            f"{s.median_total_seconds:.3f}",
            f"{s.median_p50_enqueue_ms:.3f}",
            f"{s.median_p95_enqueue_ms:.3f}",
            f"{s.median_p99_enqueue_ms:.3f}",
            f"{s.median_max_enqueue_ms:.3f}",
            f"{s.ok_runs}/{s.requested_runs}",
            style=row_style,
        )

    return table


def _runs_table(framework: str, runs: list[BenchmarkResult]) -> Table:
    """Build a Rich Table for per-run detail."""
    table = Table(
        title=f"[bold]{framework}[/bold] [dim]· per-run detail[/dim]",
        title_justify="left",
        box=SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
        padding=(0, 2),
        expand=False,
    )

    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Jobs/s", justify="right", no_wrap=True)
    table.add_column("Enqueue (s)", justify="right", no_wrap=True)
    table.add_column("Drain (s)", justify="right", no_wrap=True)
    table.add_column("Total (s)", justify="right", no_wrap=True)
    table.add_column("p50 (ms)", justify="right", no_wrap=True, header_style="dim")
    table.add_column("p95 (ms)", justify="right", no_wrap=True, header_style="dim")
    table.add_column("p99 (ms)", justify="right", no_wrap=True, header_style="dim")
    table.add_column("max (ms)", justify="right", no_wrap=True, header_style="dim")

    for idx, run in enumerate(runs, start=1):
        status_text = Text(run.status)
        if run.status == "ok":
            status_text.stylize("green")
        else:
            status_text.stylize("red")

        table.add_row(
            str(idx),
            status_text,
            f"{run.jobs_per_second:,.0f}",
            f"{run.enqueue_seconds:.3f}",
            f"{run.drain_seconds:.3f}",
            f"{run.total_seconds:.3f}",
            f"{run.p50_enqueue_ms:.3f}",
            f"{run.p95_enqueue_ms:.3f}",
            f"{run.p99_enqueue_ms:.3f}",
            f"{run.max_enqueue_ms:.3f}",
        )

    return table


def print_report(
    summaries: list[FrameworkSummary],
    *,
    config: dict[str, Any],
    runs_by_framework: dict[str, list[BenchmarkResult]] | None = None,
    warmups: int = 0,
) -> None:
    """Print the full human-readable benchmark report."""
    # Use a wide console so tables are never truncated.
    out = Console(highlight=False, width=max(console.width, 120))

    out.print()
    out.print(_config_panel(config))
    out.print()
    out.print(_summary_table(summaries))

    if warmups > 0:
        out.print(
            f"\n  [dim]{warmups} warmup(s) per framework (excluded from summary)[/dim]"
        )

    if runs_by_framework:
        for framework, runs in runs_by_framework.items():
            out.print()
            out.print(_runs_table(framework, runs))

    out.print()


# ---------------------------------------------------------------------------
# JSON (unchanged — used by --json / CI)
# ---------------------------------------------------------------------------


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
