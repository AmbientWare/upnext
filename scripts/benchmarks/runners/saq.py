from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from ..models import BenchmarkConfig, BenchmarkResult, BenchmarkWorkload
from .base import FrameworkRunner
from .common import (
    async_produce_jobs,
    async_produce_jobs_sustained,
    load_queue_wait_samples_async,
    now,
    record_queue_wait_async,
    wait_for_counter_async,
)


class SaqRunner(FrameworkRunner):
    framework = "saq"

    async def _run_async(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        try:
            from redis.asyncio import Redis as AsyncRedis
            from saq import Queue, Worker
        except Exception as exc:
            return self._skip(cfg, f"Dependency missing: {exc}")

        done_client = AsyncRedis.from_url(cfg.redis_url, decode_responses=False)
        await done_client.delete(cfg.done_key, cfg.queue_wait_key)
        task_done_client = AsyncRedis.from_url(cfg.redis_url, decode_responses=False)

        queue_name = f"bench_saq_{cfg.run_id}"
        task_name = f"bench_task_{cfg.run_id}"
        producer_queue = Queue.from_url(cfg.redis_url, name=queue_name)
        worker_queue = Queue.from_url(cfg.redis_url, name=queue_name)

        async def bench_task(
            ctx: Any,  # noqa: ARG001
            payload: dict[str, Any],
            done_key: str,
            redis_url: str,
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

        worker = Worker(
            queue=worker_queue,
            functions=[(task_name, bench_task)],
            concurrency=max(1, cfg.concurrency),
            dequeue_timeout=0.1,
        )

        async def run_worker() -> None:
            await worker_queue.connect()
            try:
                await worker.start()
            finally:
                with contextlib.suppress(Exception):
                    await worker_queue.disconnect()

        worker_task: asyncio.Task[None] | None = None
        try:
            await producer_queue.connect()
            worker_task = asyncio.create_task(run_worker())
            # Allow the worker loop to initialize consumers before enqueue starts.
            await asyncio.sleep(0.2)

            run_start = now()

            async def submit_one(idx: int) -> None:
                job = await producer_queue.enqueue(
                    task_name,
                    payload={
                        "payload": cfg.payload,
                        "submitted_at_ns": time.perf_counter_ns(),
                        "sampled": cfg.should_sample_queue_wait(idx),
                    },
                    done_key=cfg.done_key,
                    redis_url=cfg.redis_url,
                )
                if job is None:
                    raise RuntimeError("SAQ enqueue returned no job")

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
                    f"producer_concurrency={cfg.producer_concurrency}; "
                    f"worker_concurrency={cfg.concurrency}; "
                    f"workload={cfg.workload.value}; "
                    f"arrival_rate={cfg.arrival_rate}"
                ),
                framework_version=self._framework_version("saq"),
                diagnostics={
                    "worker_concurrency": cfg.concurrency,
                    "workload": cfg.workload.value,
                    "arrival_rate": cfg.arrival_rate,
                    "duration_seconds": cfg.duration_seconds,
                    "queue_wait_sample_rate": cfg.queue_wait_sample_rate,
                    "queue_wait_samples": len(queue_wait_samples),
                },
            )
        except Exception as exc:
            return self._error(cfg, f"SAQ benchmark failed: {exc}")
        finally:
            with contextlib.suppress(Exception):
                await worker.stop()
            if worker_task is not None:
                if not worker_task.done():
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(worker_task, timeout=5.0)
                if not worker_task.done():
                    worker_task.cancel()
                with contextlib.suppress(Exception):
                    await worker_task
            with contextlib.suppress(Exception):
                await producer_queue.disconnect()
            await task_done_client.aclose()
            await done_client.aclose()

    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        return asyncio.run(self._run_async(cfg))
