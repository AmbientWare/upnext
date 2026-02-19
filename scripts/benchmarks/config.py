from __future__ import annotations

from dataclasses import dataclass

from .models import BenchmarkWorkload, SUPPORTED_FRAMEWORKS


@dataclass(frozen=True)
class WorkloadPreset:
    name: str
    jobs: int
    duration_seconds: float
    arrival_rate: float
    concurrency: int
    producer_concurrency: int
    timeout_seconds: float


WORKLOAD_PRESETS: dict[BenchmarkWorkload, WorkloadPreset] = {
    BenchmarkWorkload.SUSTAINED: WorkloadPreset(
        name="sustained",
        jobs=0,
        duration_seconds=60.0,
        arrival_rate=200.0,
        concurrency=32,
        producer_concurrency=16,
        timeout_seconds=240.0,
    ),
    BenchmarkWorkload.BURST: WorkloadPreset(
        name="burst",
        jobs=10_000,
        duration_seconds=0.0,
        arrival_rate=0.0,
        concurrency=32,
        producer_concurrency=32,
        timeout_seconds=180.0,
    ),
}


@dataclass(frozen=True)
class MatrixSettings:
    workload: BenchmarkWorkload
    frameworks: list[str]
    jobs: int
    concurrency: int
    payload_bytes: int
    producer_concurrency: int
    consumer_prefetch: int
    timeout_seconds: float
    arrival_rate: float
    duration_seconds: float
    repeats: int
    warmups: int
    redis_url: str
    seed: int
    queue_wait_sample_rate: float
    queue_wait_max_samples: int


def parse_frameworks(raw: list[str] | None) -> list[str]:
    if not raw:
        return list(SUPPORTED_FRAMEWORKS)

    frameworks: list[str] = []
    for chunk in raw:
        for item in chunk.split(","):
            candidate = item.strip().lower()
            if not candidate:
                continue
            if candidate not in SUPPORTED_FRAMEWORKS:
                supported = ", ".join(SUPPORTED_FRAMEWORKS)
                raise ValueError(
                    f"Unsupported framework '{candidate}'. Expected one of: {supported}"
                )
            if candidate not in frameworks:
                frameworks.append(candidate)
    if not frameworks:
        raise ValueError("At least one framework must be provided")
    return frameworks


def resolve_workload_parameters(
    *,
    workload: BenchmarkWorkload,
    jobs: int | None,
    duration_seconds: float | None,
    arrival_rate: float | None,
    concurrency: int | None,
    producer_concurrency: int | None,
    timeout_seconds: float | None,
) -> tuple[int, int, int, float, float, float]:
    preset = WORKLOAD_PRESETS[workload]

    resolved_concurrency = (
        int(concurrency) if concurrency is not None and concurrency > 0 else preset.concurrency
    )
    resolved_timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds > 0
        else preset.timeout_seconds
    )
    resolved_producer_concurrency = (
        int(producer_concurrency)
        if producer_concurrency is not None and producer_concurrency > 0
        else preset.producer_concurrency
    )
    if resolved_producer_concurrency <= 0:
        resolved_producer_concurrency = resolved_concurrency

    if workload == BenchmarkWorkload.BURST:
        resolved_jobs = int(jobs) if jobs is not None and jobs > 0 else preset.jobs
        return (
            resolved_jobs,
            resolved_concurrency,
            resolved_producer_concurrency,
            resolved_timeout,
            0.0,
            0.0,
        )

    resolved_duration = (
        float(duration_seconds)
        if duration_seconds is not None and duration_seconds > 0
        else preset.duration_seconds
    )
    resolved_arrival_rate = (
        float(arrival_rate)
        if arrival_rate is not None and arrival_rate > 0
        else preset.arrival_rate
    )
    resolved_jobs = (
        int(jobs)
        if jobs is not None and jobs > 0
        else max(1, int(round(resolved_duration * resolved_arrival_rate)))
    )
    return (
        resolved_jobs,
        resolved_concurrency,
        resolved_producer_concurrency,
        resolved_timeout,
        resolved_arrival_rate,
        resolved_duration,
    )


def validate_common_numeric_args(
    *,
    workload: BenchmarkWorkload,
    jobs: int,
    concurrency: int,
    payload_bytes: int,
    producer_concurrency: int,
    consumer_prefetch: int,
    timeout_seconds: float,
    arrival_rate: float,
    duration_seconds: float,
    repeats: int,
    warmups: int,
    queue_wait_sample_rate: float,
    queue_wait_max_samples: int,
) -> None:
    if jobs <= 0:
        raise ValueError("jobs must be > 0")
    if workload == BenchmarkWorkload.SUSTAINED:
        if duration_seconds <= 0:
            raise ValueError("duration-seconds must be > 0 for sustained workload")
        if arrival_rate <= 0:
            raise ValueError("arrival-rate must be > 0 for sustained workload")
    if concurrency <= 0:
        raise ValueError("concurrency must be > 0")
    if payload_bytes <= 0:
        raise ValueError("payload-bytes must be > 0")
    if producer_concurrency <= 0:
        raise ValueError("producer-concurrency must be > 0")
    if consumer_prefetch < 0:
        raise ValueError("consumer-prefetch must be >= 0")
    if repeats <= 0:
        raise ValueError("repeats must be > 0")
    if warmups < 0:
        raise ValueError("warmups must be >= 0")
    if timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be > 0")
    if not 0.0 <= queue_wait_sample_rate <= 1.0:
        raise ValueError("queue-wait-sample-rate must be between 0 and 1")
    if queue_wait_max_samples < 0:
        raise ValueError("queue-wait-max-samples must be >= 0")


def resolve_consumer_prefetch(
    *,
    consumer_prefetch: int,
    concurrency: int,
) -> int:
    if consumer_prefetch > 0:
        return consumer_prefetch
    return max(1, concurrency)
