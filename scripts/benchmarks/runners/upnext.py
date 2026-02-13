from __future__ import annotations

import asyncio

from ..models import BenchmarkConfig, BenchmarkProfile, BenchmarkResult
from .base import FrameworkRunner
from .common import async_produce_jobs, effective_prefetch, now, wait_for_counter_async


class UpnextRunner(FrameworkRunner):
    framework = "upnext"

    async def _run_async(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        try:
            from redis.asyncio import Redis as AsyncRedis
            from upnext.sdk.worker import Worker
        except Exception as exc:
            return self._skip(cfg, f"Dependency missing: {exc}")

        done_client = AsyncRedis.from_url(cfg.redis_url, decode_responses=False)
        await done_client.delete(cfg.done_key)
        task_done_client = AsyncRedis.from_url(cfg.redis_url, decode_responses=False)

        prefetch = effective_prefetch(cfg)
        queue_batch_size = 100
        queue_inbox_size = max(1, cfg.concurrency + prefetch)
        queue_outbox_size = 10_000
        queue_flush_interval_ms = 5.0
        if cfg.profile == BenchmarkProfile.THROUGHPUT:
            queue_batch_size = 200
            queue_outbox_size = 20_000
            queue_flush_interval_ms = 20.0
        worker = Worker(
            name=f"bench-upnext-{cfg.run_id}",
            concurrency=max(1, cfg.concurrency),
            prefetch=prefetch,
            queue_batch_size=queue_batch_size,
            queue_inbox_size=queue_inbox_size,
            queue_outbox_size=queue_outbox_size,
            queue_flush_interval_ms=queue_flush_interval_ms,
            redis_url=cfg.redis_url,
            handle_signals=False,
        )
        worker_task: asyncio.Task[None] | None = None

        @worker.task(
            name=f"bench_task_{cfg.run_id}", timeout=max(15.0, cfg.timeout_seconds)
        )
        async def bench_task(payload: str, done_key: str, redis_url: str) -> None:
            _ = payload, redis_url
            await task_done_client.incr(done_key)

        try:
            worker_task = asyncio.create_task(worker.start())
            for _ in range(400):
                if getattr(bench_task, "_queue", None) is not None:
                    break
                await asyncio.sleep(0.01)
            else:
                raise RuntimeError("UpNext worker did not initialize task queue in time")

            run_start = now()
            enqueue_seconds, enqueue_latencies = await async_produce_jobs(
                total_jobs=cfg.jobs,
                producer_concurrency=cfg.producer_concurrency,
                submit_one=lambda: bench_task.submit(
                    payload=cfg.payload,
                    done_key=cfg.done_key,
                    redis_url=cfg.redis_url,
                ),
            )

            await wait_for_counter_async(
                done_client,
                cfg.done_key,
                cfg.jobs,
                timeout_seconds=cfg.timeout_seconds,
            )
            total_seconds = now() - run_start

            return self._result_from_timings(
                cfg=cfg,
                enqueue_seconds=enqueue_seconds,
                total_seconds=total_seconds,
                enqueue_latencies=enqueue_latencies,
                notes=(
                    f"producer_concurrency={cfg.producer_concurrency}; "
                    f"consumer_prefetch={prefetch}; "
                    f"queue_batch_size={queue_batch_size}; "
                    f"queue_inbox_size={queue_inbox_size}; "
                    f"queue_outbox_size={queue_outbox_size}; "
                    f"queue_flush_interval_ms={queue_flush_interval_ms:g}"
                ),
                framework_version=self._framework_version("upnext"),
            )
        except Exception as exc:
            return self._error(cfg, f"UpNext benchmark failed: {exc}")
        finally:
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
            await task_done_client.aclose()
            await done_client.aclose()

    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        return asyncio.run(self._run_async(cfg))
