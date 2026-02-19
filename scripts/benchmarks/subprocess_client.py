from __future__ import annotations

import subprocess
import sys

from .io import extract_marked_json
from .models import BenchmarkConfig, BenchmarkResult, DiagnosticValue, SCHEMA_VERSION


class SubprocessBenchmarkClient:
    """Runs one benchmark sample in a clean subprocess."""

    def __init__(self, *, module_name: str = "scripts.benchmarks") -> None:
        self._module_name = module_name

    def run_once(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        cmd = [
            sys.executable,
            "-m",
            self._module_name,
            "run",
            "--framework",
            cfg.framework,
            "--workload",
            cfg.workload.value,
            "--jobs",
            str(cfg.jobs),
            "--duration-seconds",
            str(cfg.duration_seconds),
            "--arrival-rate",
            str(cfg.arrival_rate),
            "--concurrency",
            str(cfg.concurrency),
            "--payload-bytes",
            str(cfg.payload_bytes),
            "--producer-concurrency",
            str(cfg.producer_concurrency),
            "--consumer-prefetch",
            str(cfg.consumer_prefetch),
            "--timeout-seconds",
            str(cfg.timeout_seconds),
            "--redis-url",
            cfg.redis_url,
            "--run-id",
            cfg.run_id,
            "--queue-wait-sample-rate",
            str(cfg.queue_wait_sample_rate),
            "--queue-wait-max-samples",
            str(cfg.queue_wait_max_samples),
            "--json",
        ]

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=max(60.0, cfg.timeout_seconds + 60.0),
        )

        if proc.returncode != 0:
            stderr_tail = proc.stderr.strip()[-700:]
            stdout_tail = proc.stdout.strip()[-700:]
            note = f"Subprocess failed ({proc.returncode})"
            if stderr_tail:
                note += f": {stderr_tail}"
            elif stdout_tail:
                note += f": {stdout_tail}"
            return BenchmarkResult.empty(cfg, status="error", notes=note)

        try:
            payload = extract_marked_json(proc.stdout)
            result_payload = payload.get("result")
            if not isinstance(result_payload, dict):
                raise TypeError("Expected object in 'result'")
            return self._benchmark_result_from_payload(cfg, result_payload)
        except Exception as exc:
            stdout_tail = proc.stdout.strip()[-700:]
            return BenchmarkResult.empty(
                cfg,
                status="error",
                notes=f"Failed to parse subprocess output: {exc}; tail={stdout_tail}",
            )

    @staticmethod
    def _benchmark_result_from_payload(
        cfg: BenchmarkConfig,
        payload: dict[str, object],
    ) -> BenchmarkResult:
        diagnostics: dict[str, DiagnosticValue] = {}
        raw_diagnostics = payload.get("diagnostics")
        if isinstance(raw_diagnostics, dict):
            for key, value in raw_diagnostics.items():
                if isinstance(value, str | int | float | bool):
                    diagnostics[str(key)] = value

        return BenchmarkResult(
            schema_version=SubprocessBenchmarkClient._coerce_int(
                payload.get("schema_version"),
                default=SCHEMA_VERSION,
            ),
            framework=str(payload.get("framework", cfg.framework)),
            status=str(payload.get("status", "error")),
            workload=str(payload.get("workload", cfg.workload.value)),
            jobs=SubprocessBenchmarkClient._coerce_int(payload.get("jobs"), default=cfg.jobs),
            concurrency=SubprocessBenchmarkClient._coerce_int(
                payload.get("concurrency"),
                default=cfg.concurrency,
            ),
            producer_concurrency=SubprocessBenchmarkClient._coerce_int(
                payload.get("producer_concurrency"),
                default=cfg.producer_concurrency,
            ),
            consumer_prefetch=SubprocessBenchmarkClient._coerce_int(
                payload.get("consumer_prefetch"),
                default=cfg.consumer_prefetch,
            ),
            timeout_seconds=SubprocessBenchmarkClient._coerce_float(
                payload.get("timeout_seconds"),
                default=cfg.timeout_seconds,
            ),
            arrival_rate=SubprocessBenchmarkClient._coerce_float(
                payload.get("arrival_rate"),
                default=cfg.arrival_rate,
            ),
            duration_seconds=SubprocessBenchmarkClient._coerce_float(
                payload.get("duration_seconds"),
                default=cfg.duration_seconds,
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
            p50_queue_wait_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("p50_queue_wait_ms"),
                default=0.0,
            ),
            p95_queue_wait_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("p95_queue_wait_ms"),
                default=0.0,
            ),
            p99_queue_wait_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("p99_queue_wait_ms"),
                default=0.0,
            ),
            max_queue_wait_ms=SubprocessBenchmarkClient._coerce_float(
                payload.get("max_queue_wait_ms"),
                default=0.0,
            ),
            queue_wait_samples=SubprocessBenchmarkClient._coerce_int(
                payload.get("queue_wait_samples"),
                default=0,
            ),
            notes=str(payload.get("notes", "")),
            framework_version=str(payload.get("framework_version", "")),
            diagnostics=diagnostics,
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
