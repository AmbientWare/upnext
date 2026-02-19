from __future__ import annotations

import math
import time
from typing import Any

from redis import Redis

from ..models import BenchmarkConfig, BenchmarkResult, BenchmarkWorkload
from .base import FrameworkRunner
from .common import (
    effective_prefetch,
    load_queue_wait_samples_sync,
    now,
    record_queue_wait_sync,
    threaded_produce_jobs,
    threaded_produce_jobs_sustained,
    wait_for_counter_sync,
)


class CeleryRunner(FrameworkRunner):
    framework = "celery"

    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        try:
            from celery import Celery
            from celery.contrib.testing.worker import start_worker
        except Exception as exc:
            return self._skip(cfg, f"Dependency missing: {exc}")

        done_client = Redis.from_url(cfg.redis_url, decode_responses=False)
        done_client.delete(cfg.done_key, cfg.queue_wait_key)
        task_done_client = Redis.from_url(cfg.redis_url, decode_responses=False)

        queue_name = f"bench.celery.{cfg.run_id}"
        target_prefetch = effective_prefetch(cfg)
        worker_prefetch_multiplier = max(
            1,
            math.ceil(target_prefetch / max(1, cfg.concurrency)),
        )

        app = Celery(f"bench_{cfg.run_id}", broker=cfg.redis_url)
        app.conf.update(
            task_default_queue=queue_name,
            task_ignore_result=True,
            worker_prefetch_multiplier=worker_prefetch_multiplier,
            task_acks_late=True,
            task_reject_on_worker_lost=True,
        )

        @app.task(name=f"bench_task_{cfg.run_id}")
        def bench_task(payload: dict[str, Any], done_key: str, redis_url: str) -> None:
            _ = redis_url
            task_done_client.incr(done_key)

            sampled = bool(payload.get("sampled", False))
            submitted_at_ns = int(payload.get("submitted_at_ns", 0) or 0)
            if sampled and submitted_at_ns > 0:
                wait_ms = (time.perf_counter_ns() - submitted_at_ns) / 1_000_000.0
                record_queue_wait_sync(
                    task_done_client,
                    cfg.queue_wait_key,
                    wait_ms,
                    max_samples=cfg.queue_wait_max_samples,
                )

        try:
            with start_worker(
                app,
                concurrency=max(1, cfg.concurrency),
                pool="threads",
                perform_ping_check=False,
                loglevel="WARNING",
            ):
                run_start = now()

                def submit_one(idx: int) -> None:
                    getattr(bench_task, "delay")(
                        {
                            "payload": cfg.payload,
                            "submitted_at_ns": time.perf_counter_ns(),
                            "sampled": cfg.should_sample_queue_wait(idx),
                        },
                        cfg.done_key,
                        cfg.redis_url,
                    )

                if cfg.workload == BenchmarkWorkload.SUSTAINED:
                    enqueue_seconds, enqueue_latencies = threaded_produce_jobs_sustained(
                        total_jobs=cfg.jobs,
                        arrival_rate=cfg.arrival_rate,
                        producer_concurrency=cfg.producer_concurrency,
                        submit_one=submit_one,
                    )
                else:
                    enqueue_seconds, enqueue_latencies = threaded_produce_jobs(
                        total_jobs=cfg.jobs,
                        producer_concurrency=cfg.producer_concurrency,
                        submit_one=submit_one,
                    )
                wait_for_counter_sync(
                    done_client,
                    cfg.done_key,
                    cfg.jobs,
                    timeout_seconds=cfg.timeout_seconds,
                )
                queue_wait_samples = load_queue_wait_samples_sync(
                    done_client,
                    cfg.queue_wait_key,
                )
                total_seconds = now() - run_start
        except Exception as exc:
            return self._error(cfg, f"Celery benchmark failed: {exc}")
        finally:
            done_client.close()
            task_done_client.close()

        return self._result_from_timings(
            cfg=cfg,
            enqueue_seconds=enqueue_seconds,
            total_seconds=total_seconds,
            enqueue_latencies_seconds=enqueue_latencies,
            queue_wait_ms_samples=queue_wait_samples,
            notes=(
                f"producer_concurrency={cfg.producer_concurrency}; "
                f"worker_prefetch_multiplier={worker_prefetch_multiplier}; "
                f"workload={cfg.workload.value}; "
                f"arrival_rate={cfg.arrival_rate}; "
                "task_acks_late=true"
            ),
            framework_version=self._framework_version("celery"),
            diagnostics={
                "worker_prefetch_multiplier": worker_prefetch_multiplier,
                "workload": cfg.workload.value,
                "arrival_rate": cfg.arrival_rate,
                "duration_seconds": cfg.duration_seconds,
                "task_acks_late": True,
                "queue_wait_sample_rate": cfg.queue_wait_sample_rate,
                "queue_wait_samples": len(queue_wait_samples),
            },
        )
