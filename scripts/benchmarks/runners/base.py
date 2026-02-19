from __future__ import annotations

from abc import ABC, abstractmethod
from importlib.metadata import version
from typing import ClassVar

from ..models import BenchmarkConfig, BenchmarkResult
from .common import max_ms, p50_ms, p95_ms, p99_ms


class FrameworkRunner(ABC):
    """Base class for framework-specific benchmark runners."""

    framework: ClassVar[str]

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
        enqueue_latencies: list[float],
        notes: str = "",
        framework_version: str = "",
    ) -> BenchmarkResult:
        total = max(total_seconds, 1e-9)
        enqueue = max(enqueue_seconds, 0.0)
        return BenchmarkResult(
            framework=cfg.framework,
            status="ok",
            jobs=cfg.jobs,
            concurrency=cfg.concurrency,
            enqueue_seconds=enqueue,
            drain_seconds=max(0.0, total - enqueue),
            total_seconds=total,
            jobs_per_second=cfg.jobs / total,
            p50_enqueue_ms=p50_ms(enqueue_latencies),
            p95_enqueue_ms=p95_ms(enqueue_latencies),
            p99_enqueue_ms=p99_ms(enqueue_latencies),
            max_enqueue_ms=max_ms(enqueue_latencies),
            notes=notes,
            framework_version=framework_version,
        )

    def _skip(self, cfg: BenchmarkConfig, notes: str) -> BenchmarkResult:
        return BenchmarkResult(
            framework=cfg.framework,
            status="skipped",
            jobs=cfg.jobs,
            concurrency=cfg.concurrency,
            enqueue_seconds=0.0,
            drain_seconds=0.0,
            total_seconds=0.0,
            jobs_per_second=0.0,
            p50_enqueue_ms=0.0,
            p95_enqueue_ms=0.0,
            p99_enqueue_ms=0.0,
            max_enqueue_ms=0.0,
            notes=notes,
        )

    def _error(self, cfg: BenchmarkConfig, notes: str) -> BenchmarkResult:
        return BenchmarkResult(
            framework=cfg.framework,
            status="error",
            jobs=cfg.jobs,
            concurrency=cfg.concurrency,
            enqueue_seconds=0.0,
            drain_seconds=0.0,
            total_seconds=0.0,
            jobs_per_second=0.0,
            p50_enqueue_ms=0.0,
            p95_enqueue_ms=0.0,
            p99_enqueue_ms=0.0,
            max_enqueue_ms=0.0,
            notes=notes,
        )

    @abstractmethod
    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        raise NotImplementedError
