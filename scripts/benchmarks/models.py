from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 3
SUPPORTED_FRAMEWORKS = ("upnext-async", "upnext-sync", "celery", "saq")


class BenchmarkWorkload(StrEnum):
    SUSTAINED = "sustained"
    BURST = "burst"


SUPPORTED_WORKLOADS = tuple(BenchmarkWorkload)
DiagnosticValue = str | int | float | bool


@dataclass(frozen=True)
class BenchmarkConfig:
    framework: str
    workload: BenchmarkWorkload
    jobs: int
    concurrency: int
    payload_bytes: int
    producer_concurrency: int
    consumer_prefetch: int
    timeout_seconds: float
    redis_url: str
    run_id: str
    arrival_rate: float = 0.0
    duration_seconds: float = 0.0
    queue_wait_sample_rate: float = 0.10
    queue_wait_max_samples: int = 5_000

    @property
    def payload(self) -> str:
        return "x" * max(1, self.payload_bytes)

    @property
    def done_key(self) -> str:
        return f"upnext:bench:{self.framework}:{self.run_id}:done"

    @property
    def queue_wait_key(self) -> str:
        return f"upnext:bench:{self.framework}:{self.run_id}:queue_wait_ms"

    @property
    def sample_every(self) -> int:
        if self.queue_wait_sample_rate <= 0:
            return 0
        if self.queue_wait_sample_rate >= 1:
            return 1
        return max(1, int(round(1.0 / self.queue_wait_sample_rate)))

    def should_sample_queue_wait(self, job_index: int) -> bool:
        every = self.sample_every
        if every <= 0:
            return False
        if every == 1:
            return True
        return job_index % every == 0

    def runtime_config(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "framework": self.framework,
            "workload": self.workload.value,
            "jobs": self.jobs,
            "concurrency": self.concurrency,
            "payload_bytes": self.payload_bytes,
            "producer_concurrency": self.producer_concurrency,
            "consumer_prefetch": self.consumer_prefetch,
            "timeout_seconds": self.timeout_seconds,
            "redis_url": self.redis_url,
            "arrival_rate": self.arrival_rate,
            "duration_seconds": self.duration_seconds,
            "queue_wait_sample_rate": self.queue_wait_sample_rate,
            "queue_wait_max_samples": self.queue_wait_max_samples,
        }


@dataclass(frozen=True)
class BenchmarkResult:
    schema_version: int
    framework: str
    status: str
    workload: str
    jobs: int
    concurrency: int
    producer_concurrency: int
    consumer_prefetch: int
    timeout_seconds: float
    arrival_rate: float
    duration_seconds: float
    enqueue_seconds: float
    drain_seconds: float
    total_seconds: float
    jobs_per_second: float
    p50_enqueue_ms: float
    p95_enqueue_ms: float
    p99_enqueue_ms: float
    max_enqueue_ms: float
    p50_queue_wait_ms: float
    p95_queue_wait_ms: float
    p99_queue_wait_ms: float
    max_queue_wait_ms: float
    queue_wait_samples: int
    notes: str = ""
    framework_version: str = ""
    diagnostics: dict[str, DiagnosticValue] = field(default_factory=dict)

    @classmethod
    def empty(
        cls,
        cfg: BenchmarkConfig,
        *,
        status: str,
        notes: str,
        diagnostics: dict[str, DiagnosticValue] | None = None,
    ) -> BenchmarkResult:
        return cls(
            schema_version=SCHEMA_VERSION,
            framework=cfg.framework,
            status=status,
            workload=cfg.workload.value,
            jobs=cfg.jobs,
            concurrency=cfg.concurrency,
            producer_concurrency=cfg.producer_concurrency,
            consumer_prefetch=cfg.consumer_prefetch,
            timeout_seconds=cfg.timeout_seconds,
            arrival_rate=cfg.arrival_rate,
            duration_seconds=cfg.duration_seconds,
            enqueue_seconds=0.0,
            drain_seconds=0.0,
            total_seconds=0.0,
            jobs_per_second=0.0,
            p50_enqueue_ms=0.0,
            p95_enqueue_ms=0.0,
            p99_enqueue_ms=0.0,
            max_enqueue_ms=0.0,
            p50_queue_wait_ms=0.0,
            p95_queue_wait_ms=0.0,
            p99_queue_wait_ms=0.0,
            max_queue_wait_ms=0.0,
            queue_wait_samples=0,
            notes=notes,
            diagnostics=diagnostics or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrameworkSummary:
    framework: str
    workload: str
    requested_runs: int
    ok_runs: int
    non_ok_count: int
    median_jobs_per_second: float
    mean_jobs_per_second: float
    stdev_jobs_per_second: float
    median_total_seconds: float
    median_p95_enqueue_ms: float
    median_p95_queue_wait_ms: float
    median_max_enqueue_ms: float
    median_max_queue_wait_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatrixRunRecord:
    run_index: int
    phase: str
    framework: str
    result: BenchmarkResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index,
            "phase": self.phase,
            "framework": self.framework,
            "result": self.result.to_dict(),
        }
