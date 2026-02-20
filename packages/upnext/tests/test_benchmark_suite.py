from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmarks.config import (  # noqa: E402
    MatrixSettings,
    parse_frameworks,
    resolve_workload_parameters,
)
from scripts.benchmarks.engine import MatrixEngine  # noqa: E402
from scripts.benchmarks.io import extract_marked_json, load_matrix_payloads  # noqa: E402
from scripts.benchmarks.models import (  # noqa: E402
    BenchmarkConfig,
    BenchmarkResult,
    BenchmarkWorkload,
)
from scripts.benchmarks.runners.common import (  # noqa: E402
    await_worker_readiness_async,
    await_worker_readiness_sync,
)


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_once(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        self.calls.append(cfg.framework)
        value = 1000.0 if cfg.framework == "upnext-async" else 500.0
        return BenchmarkResult(
            schema_version=3,
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
            enqueue_seconds=1.0,
            drain_seconds=1.0,
            total_seconds=2.0,
            jobs_per_second=value,
            p50_enqueue_ms=1.0,
            p95_enqueue_ms=2.0,
            p99_enqueue_ms=3.0,
            max_enqueue_ms=4.0,
            p50_queue_wait_ms=1.0,
            p95_queue_wait_ms=2.0,
            p99_queue_wait_ms=3.0,
            max_queue_wait_ms=4.0,
            queue_wait_samples=10,
            diagnostics={"fake": True},
        )


def test_parse_frameworks_deduplicates_and_validates() -> None:
    out = parse_frameworks(["upnext-async, celery", "celery", "upnext-sync"])
    assert out == ["upnext-async", "celery", "upnext-sync"]


def test_parse_frameworks_default_includes_saq() -> None:
    out = parse_frameworks(None)
    assert "saq" in out
    assert "dramatiq" not in out


def test_resolve_workload_sustained_derives_jobs_from_rate() -> None:
    jobs, concurrency, producers, timeout_s, arrival, duration = resolve_workload_parameters(
        workload=BenchmarkWorkload.SUSTAINED,
        jobs=None,
        duration_seconds=30.0,
        arrival_rate=100.0,
        concurrency=16,
        producer_concurrency=8,
        timeout_seconds=90.0,
    )
    assert jobs == 3000
    assert concurrency == 16
    assert producers == 8
    assert timeout_s == 90.0
    assert arrival == 100.0
    assert duration == 30.0


def test_resolve_workload_burst_uses_defaults() -> None:
    jobs, concurrency, producers, timeout_s, arrival, duration = resolve_workload_parameters(
        workload=BenchmarkWorkload.BURST,
        jobs=None,
        duration_seconds=None,
        arrival_rate=None,
        concurrency=None,
        producer_concurrency=None,
        timeout_seconds=None,
    )
    assert jobs == 10000
    assert concurrency == 32
    assert producers == 32
    assert timeout_s == 180.0
    assert arrival == 0.0
    assert duration == 0.0


def test_extract_marked_json_parses_payload() -> None:
    payload = extract_marked_json(
        "before\n===BENCHMARK_JSON_START===\n{\"x\": 1}\n===BENCHMARK_JSON_END===\nafter"
    )
    assert payload == {"x": 1}


def test_load_matrix_payloads_supports_flat_results_directory(tmp_path: Path) -> None:
    sustained_path = tmp_path / "benchmark-sustained.json"
    burst_path = tmp_path / "benchmark-burst.json"
    non_matrix_path = tmp_path / "benchmark-summary.json"

    sustained_path.write_text(
        '{"kind":"benchmark-matrix","config":{"workload":"sustained"},"summaries":[]}\n'
    )
    burst_path.write_text(
        '{"kind":"benchmark-matrix","config":{"workload":"burst"},"summaries":[]}\n'
    )
    non_matrix_path.write_text('{"kind":"benchmark-summary"}\n')

    payloads = load_matrix_payloads(tmp_path)

    assert len(payloads) == 2
    workloads = sorted(str(item["config"]["workload"]) for item in payloads)
    assert workloads == ["burst", "sustained"]


def test_matrix_engine_interleaves_runs_deterministically() -> None:
    fake = _FakeClient()
    engine = MatrixEngine(client=fake)

    settings = MatrixSettings(
        workload=BenchmarkWorkload.SUSTAINED,
        frameworks=["upnext-async", "celery"],
        jobs=100,
        concurrency=2,
        payload_bytes=64,
        producer_concurrency=2,
        consumer_prefetch=2,
        timeout_seconds=30.0,
        arrival_rate=50.0,
        duration_seconds=2.0,
        repeats=2,
        warmups=1,
        redis_url="redis://127.0.0.1:6379/15",
        seed=7,
        queue_wait_sample_rate=0.1,
        queue_wait_max_samples=100,
    )

    execution = engine.run(settings)

    assert len(execution.warmups) == 2
    assert len(execution.runs) == 4
    assert len(execution.summaries) == 2
    assert set(fake.calls[:2]) == {"upnext-async", "celery"}
    assert set(fake.calls[2:4]) == {"upnext-async", "celery"}
    assert set(fake.calls[4:6]) == {"upnext-async", "celery"}


class _SyncCounterClient:
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self.deleted: list[str] = []

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self._values.pop(key, None)

    def get(self, key: str) -> int:
        return self._values.get(key, 0)

    def incr(self, key: str) -> int:
        self._values[key] = self._values.get(key, 0) + 1
        return self._values[key]


class _AsyncCounterClient:
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self._values.pop(key, None)

    async def get(self, key: str) -> int:
        return self._values.get(key, 0)

    async def incr(self, key: str) -> int:
        self._values[key] = self._values.get(key, 0) + 1
        return self._values[key]


def test_readiness_sync_cleans_key_on_success_and_failure() -> None:
    key = "bench:ready"

    client = _SyncCounterClient()

    def submit_ok() -> None:
        client.incr(key)

    await_worker_readiness_sync(
        client=client,
        readiness_key=key,
        timeout_seconds=0.5,
        submit_probe=submit_ok,
    )
    assert client.get(key) == 0
    assert client.deleted.count(key) == 2

    failing_client = _SyncCounterClient()

    def submit_fail() -> None:
        raise RuntimeError("probe failure")

    with pytest.raises(RuntimeError):
        await_worker_readiness_sync(
            client=failing_client,
            readiness_key=key,
            timeout_seconds=0.5,
            submit_probe=submit_fail,
        )
    assert failing_client.get(key) == 0
    assert failing_client.deleted.count(key) == 2


@pytest.mark.asyncio
async def test_readiness_async_cleans_key_on_success_and_failure() -> None:
    key = "bench:ready"

    client = _AsyncCounterClient()

    async def submit_ok() -> None:
        await client.incr(key)

    await await_worker_readiness_async(
        client=client,
        readiness_key=key,
        timeout_seconds=0.5,
        submit_probe=submit_ok,
    )
    assert await client.get(key) == 0
    assert client.deleted.count(key) == 2

    failing_client = _AsyncCounterClient()

    async def submit_fail() -> None:
        raise RuntimeError("probe failure")

    with pytest.raises(RuntimeError):
        await await_worker_readiness_async(
            client=failing_client,
            readiness_key=key,
            timeout_seconds=0.5,
            submit_probe=submit_fail,
        )
    assert await failing_client.get(key) == 0
    assert failing_client.deleted.count(key) == 2
