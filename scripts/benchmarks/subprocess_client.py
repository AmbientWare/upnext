from __future__ import annotations

import json
import subprocess
import sys

from .models import BenchmarkConfig, BenchmarkResult

JSON_START_MARKER = "===BENCHMARK_JSON_START==="
JSON_END_MARKER = "===BENCHMARK_JSON_END==="


class SubprocessBenchmarkClient:
    """Runs one benchmark sample in a clean subprocess."""

    def __init__(self, *, module_name: str = "scripts.benchmarks") -> None:
        self._module_name = module_name

    def run_once(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        cmd = [
            sys.executable,
            "-m",
            self._module_name,
            "--single-framework",
            cfg.framework,
            "--profile",
            cfg.profile.value,
            "--jobs",
            str(cfg.jobs),
            "--concurrency",
            str(cfg.concurrency),
            "--payload-bytes",
            str(cfg.payload_bytes),
            "--producer-concurrency",
            str(cfg.producer_concurrency),
            "--consumer-prefetch",
            str(cfg.consumer_prefetch),
            "--upnext-prefetch",
            str(cfg.upnext_prefetch),
            "--timeout-seconds",
            str(cfg.timeout_seconds),
            "--redis-url",
            cfg.redis_url,
            "--run-id",
            cfg.run_id,
            "--json",
        ]

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if proc.returncode != 0:
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
                notes=f"Subprocess failed ({proc.returncode}): {proc.stderr.strip()[-300:]}",
            )

        try:
            payload = self._extract_json_payload(proc.stdout)
            return self._benchmark_result_from_payload(payload)
        except Exception as exc:
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
                notes=f"Failed to parse subprocess output: {exc}",
            )

    @staticmethod
    def _benchmark_result_from_payload(payload: dict[str, object]) -> BenchmarkResult:
        return BenchmarkResult(
            framework=str(payload.get("framework", "")),
            status=str(payload.get("status", "")),
            jobs=SubprocessBenchmarkClient._coerce_int(payload.get("jobs"), default=0),
            concurrency=SubprocessBenchmarkClient._coerce_int(
                payload.get("concurrency"),
                default=0,
            ),
            enqueue_seconds=SubprocessBenchmarkClient._coerce_float(
                payload.get("enqueue_seconds"),
                default=0.0,
            ),
            drain_seconds=SubprocessBenchmarkClient._coerce_float(
                payload.get("drain_seconds"),
                default=0.0,
            ),
            total_seconds=SubprocessBenchmarkClient._coerce_float(
                payload.get("total_seconds"),
                default=0.0,
            ),
            jobs_per_second=SubprocessBenchmarkClient._coerce_float(
                payload.get("jobs_per_second"),
                default=0.0,
            ),
            p50_enqueue_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("p50_enqueue_ms"),
                default=0.0,
            ),
            p95_enqueue_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("p95_enqueue_ms"),
                default=0.0,
            ),
            p99_enqueue_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("p99_enqueue_ms"),
                default=0.0,
            ),
            max_enqueue_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("max_enqueue_ms"),
                default=0.0,
            ),
            notes=str(payload.get("notes", "")),
            framework_version=str(payload.get("framework_version", "")),
        )

    @staticmethod
    def _coerce_int(value: object | None, *, default: int) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _coerce_float(value: object | None, *, default: float) -> float:
        if value is None:
            return default
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _extract_json_payload(stdout: str) -> dict[str, object]:
        start = stdout.find(JSON_START_MARKER)
        end = stdout.find(JSON_END_MARKER)
        if start < 0 or end < 0 or end <= start:
            raise ValueError("Benchmark output markers missing")
        payload = stdout[start + len(JSON_START_MARKER) : end].strip()
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise TypeError("Expected dict payload from subprocess benchmark run")
        return raw
