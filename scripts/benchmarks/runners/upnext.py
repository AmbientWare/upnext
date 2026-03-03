from __future__ import annotations

import asyncio
import time
from typing import Any

from ..models import (
    BenchmarkConfig,
    BenchmarkProfile,
    BenchmarkResult,
    BenchmarkWorkload,
)
from .base import FrameworkRunner
from .common import (
    async_produce_jobs,
    async_produce_jobs_sustained,
    await_worker_readiness_async,
    configured_prefetch,
    load_queue_wait_samples_async,
    now,
    record_queue_wait_async,
    wait_for_counter_async,
    worker_readiness_key,
)


class UpnextAsyncRunner(FrameworkRunner):
    framework = "upnext-async"

    async def _run_async(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        try:
            from redis.asyncio import Redis as AsyncRedis
            from upnext.config import get_settings
            from upnext.sdk import Worker, WorkerQueueConfig
        except Exception as exc:
            return self._skip(cfg, f"Dependency missing: {exc}")

        settings = get_settings()
        requested_prefetch = cfg.consumer_prefetch
        target_prefetch = configured_prefetch(cfg)
        queue_config = (
            WorkerQueueConfig(
                batch_size=max(1, target_prefetch),
                inbox_size=max(1, target_prefetch),
            )
            if cfg.profile == BenchmarkProfile.THROUGHPUT
            else None
        )
        default_batch_size = max(1, int(settings.queue_batch_size))
        default_inbox_size = max(default_batch_size, int(settings.queue_inbox_size))
        effective_queue_batch_size = (
            default_batch_size if queue_config is None else max(1, target_prefetch)
        )
        effective_queue_inbox_size = (
            default_inbox_size
            if queue_config is None
            else max(effective_queue_batch_size, max(1, target_prefetch))
        )
        done_client: Any | None = None
        task_done_client: Any | None = None
        worker: Any | None = None
        worker_task: asyncio.Task[None] | None = None

        try:
            done_client = AsyncRedis.from_url(cfg.redis_url, decode_responses=False)
            await done_client.delete(cfg.done_key, cfg.queue_wait_key)
            task_done_client = AsyncRedis.from_url(
                cfg.redis_url, decode_responses=False
            )

            worker = Worker(
                name=f"bench-upnext-{cfg.run_id}",
                concurrency=max(1, cfg.concurrency),
                redis_url=cfg.redis_url,
                queue_config=queue_config,
                handle_signals=False,
            )

            @worker.task(
                name=f"bench_task_{cfg.run_id}", timeout=max(15.0, cfg.timeout_seconds)
            )
            async def bench_task(
                payload: dict[str, Any], done_key: str, redis_url: str
            ) -> None:
                _ = redis_url
                await task_done_client.incr(done_key)

                sampled = bool(payload.get("sampled", False))
                submitted_at_ns = int(payload.get("submitted_at_ns", 0) or 0)
                if sampled and submitted_at_ns > 0:
                    wait_ms = (time.perf_counter_ns() - submitted_at_ns) / 1_000_000.0
                    await record_queue_wait_async(
                        task_done_client,
                        cfg.queue_wait_key,
                        wait_ms,
                        max_samples=cfg.queue_wait_max_samples,
                    )

            worker_task = asyncio.create_task(worker.start())
            for _ in range(400):
                if getattr(bench_task, "_queue", None) is not None:
                    break
                await asyncio.sleep(0.01)
            else:
                raise RuntimeError(
                    "UpNext worker did not initialize task queue in time"
                )

            readiness_key = worker_readiness_key(cfg.done_key)

            async def submit_probe() -> None:
                await bench_task.submit(
                    payload={
                        "payload": cfg.payload,
                        "submitted_at_ns": 0,
                        "sampled": False,
                    },
                    done_key=readiness_key,
                    redis_url=cfg.redis_url,
                )

            await await_worker_readiness_async(
                client=done_client,
                readiness_key=readiness_key,
                timeout_seconds=min(30.0, cfg.timeout_seconds),
                submit_probe=submit_probe,
            )

            run_start = now()

            async def submit_one(idx: int) -> None:
                await bench_task.submit(
                    payload={
                        "payload": cfg.payload,
                        "submitted_at_ns": time.perf_counter_ns(),
                        "sampled": cfg.should_sample_queue_wait(idx),
                    },
                    done_key=cfg.done_key,
                    redis_url=cfg.redis_url,
                )

            if cfg.workload == BenchmarkWorkload.SUSTAINED:
                enqueue_seconds, enqueue_latencies = await async_produce_jobs_sustained(
                    total_jobs=cfg.jobs,
                    arrival_rate=cfg.arrival_rate,
                    producer_concurrency=cfg.producer_concurrency,
                    submit_one=submit_one,
                )
            else:
                enqueue_seconds, enqueue_latencies = await async_produce_jobs(
                    total_jobs=cfg.jobs,
                    producer_concurrency=cfg.producer_concurrency,
                    submit_one=submit_one,
                )

            await wait_for_counter_async(
                done_client,
                cfg.done_key,
                cfg.jobs,
                timeout_seconds=cfg.timeout_seconds,
            )
            queue_wait_samples = await load_queue_wait_samples_async(
                done_client,
                cfg.queue_wait_key,
            )
            total_seconds = now() - run_start

            return self._result_from_timings(
                cfg=cfg,
                enqueue_seconds=enqueue_seconds,
                total_seconds=total_seconds,
                enqueue_latencies_seconds=enqueue_latencies,
                queue_wait_ms_samples=queue_wait_samples,
                notes=(
                    f"profile={cfg.profile.value}; "
                    f"producer_concurrency={cfg.producer_concurrency}; "
                    f"consumer_prefetch_requested={requested_prefetch}; "
                    f"consumer_prefetch_effective={target_prefetch}; "
                    f"queue_batch_size={effective_queue_batch_size}; "
                    f"queue_inbox_size={effective_queue_inbox_size}; "
                    f"workload={cfg.workload.value}; "
                    f"arrival_rate={cfg.arrival_rate}"
                ),
                framework_version=self._framework_version("upnext"),
                diagnostics={
                    "consumer_prefetch_requested": requested_prefetch,
                    "consumer_prefetch_effective": target_prefetch,
                    "workload": cfg.workload.value,
                    "profile": cfg.profile.value,
                    "arrival_rate": cfg.arrival_rate,
                    "duration_seconds": cfg.duration_seconds,
                    "queue_wait_sample_rate": cfg.queue_wait_sample_rate,
                    "queue_wait_samples": len(queue_wait_samples),
                    "queue_batch_size_effective": effective_queue_batch_size,
                    "queue_inbox_size_effective": effective_queue_inbox_size,
                    "queue_override_applied": queue_config is not None,
                },
            )
        except Exception as exc:
            return self._error(cfg, f"UpNext async benchmark failed: {exc}")
        finally:
            if worker is not None:
                try:
                    await worker.stop(timeout=min(15.0, cfg.timeout_seconds))
                except Exception:
                    pass
            if worker_task is not None:
                if not worker_task.done():
                    worker_task.cancel()
                try:
                    await worker_task
                except Exception:
                    pass
            if task_done_client is not None:
                await task_done_client.aclose()
            if done_client is not None:
                await done_client.aclose()

    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        return asyncio.run(self._run_async(cfg))
