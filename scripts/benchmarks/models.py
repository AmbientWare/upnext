from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SUPPORTED_FRAMEWORKS = ("upnext-async", "upnext-sync", "celery", "dramatiq")


class BenchmarkProfile(StrEnum):
    THROUGHPUT = "throughput"
    DURABILITY = "durability"


SUPPORTED_PROFILES = tuple(BenchmarkProfile)


@dataclass(frozen=True)
class BenchmarkConfig:
    framework: str
    profile: BenchmarkProfile
    jobs: int
    concurrency: int
    payload_bytes: int
    producer_concurrency: int
    consumer_prefetch: int
    timeout_seconds: float
    redis_url: str
    run_id: str

    @property
    def payload(self) -> str:
        return "x" * max(1, self.payload_bytes)

    @property
    def done_key(self) -> str:
        return f"upnext:bench:{self.framework}:{self.run_id}:done"


@dataclass(frozen=True)
class BenchmarkResult:
    framework: str
    status: str
    jobs: int
    concurrency: int
    enqueue_seconds: float
    drain_seconds: float
    total_seconds: float
    jobs_per_second: float
    p50_enqueue_ms: float
    p95_enqueue_ms: float
    p99_enqueue_ms: float
    max_enqueue_ms: float
    notes: str = ""
    framework_version: str = ""


@dataclass(frozen=True)
class FrameworkSummary:
    framework: str
    requested_runs: int
    ok_runs: int
    median_jobs_per_second: float
    mean_jobs_per_second: float
    stdev_jobs_per_second: float
    median_total_seconds: float
    median_p50_enqueue_ms: float
    median_p95_enqueue_ms: float
    median_p99_enqueue_ms: float
    median_max_enqueue_ms: float
    non_ok_count: int
