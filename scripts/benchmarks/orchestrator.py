from __future__ import annotations

import uuid
from dataclasses import dataclass

from .models import BenchmarkConfig, BenchmarkProfile, BenchmarkResult
from .subprocess_client import SubprocessBenchmarkClient


@dataclass(frozen=True)
class BenchmarkRunSettings:
    profile: BenchmarkProfile
    jobs: int
    concurrency: int
    payload_bytes: int
    producer_concurrency: int
    consumer_prefetch: int
    timeout_seconds: float
    redis_url: str
    repeats: int
    warmups: int


class BenchmarkOrchestrator:
    """Coordinates warmups + repeated runs per framework."""

    def __init__(self, *, client: SubprocessBenchmarkClient) -> None:
        self._client = client

    def run_framework(
        self,
        framework: str,
        *,
        settings: BenchmarkRunSettings,
    ) -> tuple[list[BenchmarkResult], list[BenchmarkResult]]:
        warmups: list[BenchmarkResult] = []
        measured: list[BenchmarkResult] = []

        for _ in range(settings.warmups):
            cfg = self._make_cfg(framework, settings)
            warmups.append(self._client.run_once(cfg))

        for _ in range(settings.repeats):
            cfg = self._make_cfg(framework, settings)
            measured.append(self._client.run_once(cfg))

        return warmups, measured

    @staticmethod
    def _make_cfg(framework: str, settings: BenchmarkRunSettings) -> BenchmarkConfig:
        return BenchmarkConfig(
            framework=framework,
            profile=settings.profile,
            jobs=settings.jobs,
            concurrency=settings.concurrency,
            payload_bytes=settings.payload_bytes,
            producer_concurrency=settings.producer_concurrency,
            consumer_prefetch=settings.consumer_prefetch,
            timeout_seconds=settings.timeout_seconds,
            redis_url=settings.redis_url,
            run_id=uuid.uuid4().hex[:10],
        )
