from __future__ import annotations

import time

from redis import Redis

from ..models import BenchmarkConfig, BenchmarkProfile, BenchmarkResult
from .base import FrameworkRunner
from .common import now, threaded_produce_jobs, wait_for_counter_sync


class DramatiqRunner(FrameworkRunner):
    framework = "dramatiq"

    def run(self, cfg: BenchmarkConfig) -> BenchmarkResult:
        try:
            import dramatiq
            from dramatiq.brokers.redis import RedisBroker
        except Exception as exc:
            return self._skip(cfg, f"Dependency missing: {exc}")

        done_client = Redis.from_url(cfg.redis_url, decode_responses=False)
        done_client.delete(cfg.done_key)
        task_done_client = Redis.from_url(cfg.redis_url, decode_responses=False)

        queue_name = f"bench_dramatiq_{cfg.run_id}"
        durability_mode = cfg.profile == BenchmarkProfile.DURABILITY

        broker = RedisBroker(url=cfg.redis_url)

        # In durability mode, strip Retries middleware to match Celery's
        # task_reject_on_worker_lost (no automatic retries on failure).
        if durability_mode:
            broker.middleware = [
                m
                for m in broker.middleware
                if type(m).__name__ not in ("Retries",)
            ]

        dramatiq.set_broker(broker)

        @dramatiq.actor(
            queue_name=queue_name,
            actor_name=f"bench_actor_{cfg.run_id}",
        )
        def bench_actor(payload: str, done_key: str, redis_url: str) -> None:
            _ = payload, redis_url
            task_done_client.incr(done_key)

        try:
            worker = dramatiq.Worker(
                broker,
                worker_threads=max(1, cfg.concurrency),
            )
            worker.start()

            # Give the worker time to start consuming.
            time.sleep(0.5)

            run_start = now()
            enqueue_seconds, enqueue_latencies = threaded_produce_jobs(
                total_jobs=cfg.jobs,
                producer_concurrency=cfg.producer_concurrency,
                submit_one=lambda: getattr(
                    bench_actor,
                    "send",
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

            worker.stop()
            worker.join()
        except Exception as exc:
            return self._error(cfg, f"Dramatiq benchmark failed: {exc}")
        finally:
            done_client.close()
            task_done_client.close()
            try:
                broker.close()
            except Exception:
                pass

        return self._result_from_timings(
            cfg=cfg,
            enqueue_seconds=enqueue_seconds,
            total_seconds=total_seconds,
            enqueue_latencies=enqueue_latencies,
            notes=(
                f"producer_concurrency={cfg.producer_concurrency}; "
                f"worker_threads={cfg.concurrency}; "
                f"durability={durability_mode}"
            ),
            framework_version=self._framework_version("dramatiq"),
        )
