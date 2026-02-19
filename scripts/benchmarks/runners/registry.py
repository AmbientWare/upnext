from __future__ import annotations

from ..models import BenchmarkConfig, BenchmarkResult
from .base import FrameworkRunner
from .celery import CeleryRunner
from .common import ensure_redis
from .saq import SaqRunner
from .upnext import UpnextAsyncRunner
from .upnext_sync import UpnextSyncRunner

RUNNER_REGISTRY: dict[str, type[FrameworkRunner]] = {
    UpnextAsyncRunner.framework: UpnextAsyncRunner,
    UpnextSyncRunner.framework: UpnextSyncRunner,
    CeleryRunner.framework: CeleryRunner,
    SaqRunner.framework: SaqRunner,
}


def run_single_framework(cfg: BenchmarkConfig) -> BenchmarkResult:
    try:
        ensure_redis(cfg.redis_url)
    except Exception as exc:
        return BenchmarkResult.empty(
            cfg,
            status="error",
            notes=f"Redis unavailable ({cfg.redis_url}): {exc}",
        )

    runner_cls = RUNNER_REGISTRY.get(cfg.framework)
    if runner_cls is None:
        return BenchmarkResult.empty(
            cfg,
            status="error",
            notes=f"Unsupported framework '{cfg.framework}'",
        )

    return runner_cls().run(cfg)
