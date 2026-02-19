from __future__ import annotations

from ..models import BenchmarkConfig, BenchmarkResult, SUPPORTED_FRAMEWORKS
from .base import FrameworkRunner
from .celery import CeleryRunner
from .common import ensure_redis
from .dramatiq import DramatiqRunner
from .upnext import UpnextAsyncRunner
from .upnext_sync import UpnextSyncRunner

RUNNER_REGISTRY: dict[str, type[FrameworkRunner]] = {
    UpnextAsyncRunner.framework: UpnextAsyncRunner,
    UpnextSyncRunner.framework: UpnextSyncRunner,
    CeleryRunner.framework: CeleryRunner,
    DramatiqRunner.framework: DramatiqRunner,
}


def parse_frameworks(raw: list[str] | None) -> list[str]:
    if not raw:
        return list(SUPPORTED_FRAMEWORKS)

    names: list[str] = []
    for chunk in raw:
        for item in chunk.split(","):
            candidate = item.strip().lower()
            if not candidate:
                continue
            if candidate not in SUPPORTED_FRAMEWORKS:
                raise ValueError(
                    f"Unsupported framework '{candidate}'. "
                    f"Expected one of: {', '.join(SUPPORTED_FRAMEWORKS)}"
                )
            if candidate not in names:
                names.append(candidate)
    return names


def run_single_framework(cfg: BenchmarkConfig) -> BenchmarkResult:
    try:
        ensure_redis(cfg.redis_url)
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
            notes=f"Redis unavailable ({cfg.redis_url}): {exc}",
        )

    runner_cls = RUNNER_REGISTRY.get(cfg.framework)
    if runner_cls is None:
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
            notes=f"Unsupported framework '{cfg.framework}'",
        )

    return runner_cls().run(cfg)
