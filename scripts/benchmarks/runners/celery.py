from __future__ import annotations

import math

from redis import Redis

from ..models import BenchmarkConfig, BenchmarkProfile, BenchmarkResult
from .base import FrameworkRunner
from .common import effective_prefetch, now, threaded_produce_jobs, wait_for_counter_sync


class CeleryRunner(FrameworkRunner):
    framework = "celery"

    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        try:
            from celery import Celery
            from celery.contrib.testing.worker import start_worker
        except Exception as exc:
            return self._skip(cfg, f"Dependency missing: {exc}")

        done_client = Redis.from_url(cfg.redis_url, decode_responses=False)
        done_client.delete(cfg.done_key)
        task_done_client = Redis.from_url(cfg.redis_url, decode_responses=False)

        queue_name = f"bench.celery.{cfg.run_id}"
        target_prefetch = effective_prefetch(cfg)
        worker_prefetch_multiplier = max(
            1,
            math.ceil(target_prefetch / max(1, cfg.concurrency)),
        )
        durability_mode = cfg.profile == BenchmarkProfile.DURABILITY

        app = Celery(f"bench_{cfg.run_id}", broker=cfg.redis_url)
        app.conf.update(
            task_default_queue=queue_name,
            task_ignore_result=True,
            worker_prefetch_multiplier=worker_prefetch_multiplier,
            task_acks_late=durability_mode,
            task_reject_on_worker_lost=durability_mode,
        )

        @app.task(name=f"bench_task_{cfg.run_id}")
        def bench_task(payload: str, done_key: str, redis_url: str) -> None:
            _ = payload, redis_url
            task_done_client.incr(done_key)

        try:
            with start_worker(
                app,
                concurrency=max(1, cfg.concurrency),
                pool="threads",
                perform_ping_check=False,
                loglevel="WARNING",
            ):
                run_start = now()
                enqueue_seconds, enqueue_latencies = threaded_produce_jobs(
                    total_jobs=cfg.jobs,
                    producer_concurrency=cfg.producer_concurrency,
                    submit_one=lambda: getattr(
                        bench_task,
                        "delay",
                    )(
                        cfg.payload,
                        cfg.done_key,
                        cfg.redis_url,
                    ),
                )
                wait_for_counter_sync(
                    done_client,
                    cfg.done_key,
                    cfg.jobs,
                    timeout_seconds=cfg.timeout_seconds,
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
            enqueue_latencies=enqueue_latencies,
            notes=(
                f"producer_concurrency={cfg.producer_concurrency}; "
                f"worker_prefetch_multiplier={worker_prefetch_multiplier}; "
                f"task_acks_late={durability_mode}"
            ),
            framework_version=self._framework_version("celery"),
        )
