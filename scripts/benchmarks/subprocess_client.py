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
                p95_enqueue_ms=0.0,
                notes=f"Subprocess failed ({proc.returncode}): {proc.stderr.strip()[-300:]}",
            )

        try:
            payload = self._extract_json_payload(proc.stdout)
            return BenchmarkResult(**payload)
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
                p95_enqueue_ms=0.0,
                notes=f"Failed to parse subprocess output: {exc}",
            )

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
