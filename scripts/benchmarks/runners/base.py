from __future__ import annotations

from abc import ABC, abstractmethod
from importlib.metadata import version

from ..metrics import sample_summary, seconds_to_ms
from ..models import SCHEMA_VERSION, BenchmarkConfig, BenchmarkResult, DiagnosticValue


class FrameworkRunner(ABC):
    """Base class for framework-specific benchmark runners."""

    framework: str

    def _framework_version(self, package_name: str) -> str:
        try:
            return version(package_name)
        except Exception:
            return ""

    def _result_from_timings(
        self,
        *,
        cfg: BenchmarkConfig,
        enqueue_seconds: float,
        total_seconds: float,
        enqueue_latencies_seconds: list[float],
        queue_wait_ms_samples: list[float],
        notes: str = "",
        framework_version: str = "",
        diagnostics: dict[str, DiagnosticValue] | None = None,
    ) -> BenchmarkResult:
        total = max(total_seconds, 1e-9)
        enqueue = max(enqueue_seconds, 0.0)
        enqueue_stats = sample_summary(seconds_to_ms(enqueue_latencies_seconds))
        queue_wait_stats = sample_summary(queue_wait_ms_samples)
        return BenchmarkResult(
            schema_version=SCHEMA_VERSION,
            framework=cfg.framework,
            status="ok",
            workload=cfg.workload.value,
            jobs=cfg.jobs,
            concurrency=cfg.concurrency,
            producer_concurrency=cfg.producer_concurrency,
            consumer_prefetch=cfg.consumer_prefetch,
            timeout_seconds=cfg.timeout_seconds,
            arrival_rate=cfg.arrival_rate,
            duration_seconds=cfg.duration_seconds,
            enqueue_seconds=enqueue,
            drain_seconds=max(0.0, total - enqueue),
            total_seconds=total,
            jobs_per_second=cfg.jobs / total,
            p50_enqueue_ms=enqueue_stats["p50"],
            p95_enqueue_ms=enqueue_stats["p95"],
            p99_enqueue_ms=enqueue_stats["p99"],
            max_enqueue_ms=enqueue_stats["max"],
            p50_queue_wait_ms=queue_wait_stats["p50"],
            p95_queue_wait_ms=queue_wait_stats["p95"],
            p99_queue_wait_ms=queue_wait_stats["p99"],
            max_queue_wait_ms=queue_wait_stats["max"],
            queue_wait_samples=len(queue_wait_ms_samples),
            notes=notes,
            framework_version=framework_version,
            diagnostics=diagnostics or {},
        )

    def _skip(
        self,
        cfg: BenchmarkConfig,
        notes: str,
        diagnostics: dict[str, DiagnosticValue] | None = None,
    ) -> BenchmarkResult:
        return BenchmarkResult.empty(
            cfg,
            status="skipped",
            notes=notes,
            diagnostics=diagnostics,
        )

    def _error(
        self,
        cfg: BenchmarkConfig,
        notes: str,
        diagnostics: dict[str, DiagnosticValue] | None = None,
    ) -> BenchmarkResult:
        return BenchmarkResult.empty(
            cfg,
            status="error",
            notes=notes,
            diagnostics=diagnostics,
        )

    @abstractmethod
    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        raise NotImplementedError
