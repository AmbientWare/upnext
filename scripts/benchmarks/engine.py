from __future__ import annotations

import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from .config import MatrixSettings
from .models import BenchmarkConfig, BenchmarkResult, MatrixRunRecord
from .report_json import summarize_framework_runs
from .subprocess_client import SubprocessBenchmarkClient


class BenchmarkClient(Protocol):
    def run_once(self, cfg: BenchmarkConfig) -> BenchmarkResult: ...


@dataclass(frozen=True)
class MatrixExecution:
    settings: MatrixSettings
    warmups: list[MatrixRunRecord]
    runs: list[MatrixRunRecord]
    summaries: list


class MatrixEngine:
    """Executes warmup and measured benchmark rounds with fair interleaving."""

    def __init__(self, *, client: BenchmarkClient | None = None) -> None:
        self._client = client if client is not None else SubprocessBenchmarkClient()

    def run(self, settings: MatrixSettings) -> MatrixExecution:
        warmups: list[MatrixRunRecord] = []
        runs: list[MatrixRunRecord] = []
        measured_by_framework = defaultdict(list)
        rng = random.Random(settings.seed)

        for phase, count in (("warmup", settings.warmups), ("measured", settings.repeats)):
            for run_index in range(1, count + 1):
                order = list(settings.frameworks)
                rng.shuffle(order)
                for framework in order:
                    cfg = self._build_cfg(settings, framework)
                    result = self._client.run_once(cfg)
                    record = MatrixRunRecord(
                        run_index=run_index,
                        phase=phase,
                        framework=framework,
                        result=result,
                    )
                    if phase == "warmup":
                        warmups.append(record)
                    else:
                        runs.append(record)
                        measured_by_framework[framework].append(result)

        summaries = [
            summarize_framework_runs(
                framework=framework,
                workload=settings.workload.value,
                requested_runs=settings.repeats,
                runs=measured_by_framework.get(framework, []),
            )
            for framework in settings.frameworks
        ]

        return MatrixExecution(
            settings=settings,
            warmups=warmups,
            runs=runs,
            summaries=summaries,
        )

    @staticmethod
    def _build_cfg(settings: MatrixSettings, framework: str) -> BenchmarkConfig:
        return BenchmarkConfig(
            framework=framework,
            workload=settings.workload,
            jobs=settings.jobs,
            concurrency=settings.concurrency,
            payload_bytes=settings.payload_bytes,
            producer_concurrency=settings.producer_concurrency,
            consumer_prefetch=settings.consumer_prefetch,
            timeout_seconds=settings.timeout_seconds,
            redis_url=settings.redis_url,
            run_id=uuid.uuid4().hex[:10],
            arrival_rate=settings.arrival_rate,
            duration_seconds=settings.duration_seconds,
            queue_wait_sample_rate=settings.queue_wait_sample_rate,
            queue_wait_max_samples=settings.queue_wait_max_samples,
        )
