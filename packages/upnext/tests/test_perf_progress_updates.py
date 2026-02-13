from __future__ import annotations

from time import perf_counter

import pytest
from shared.domain import Job
from upnext.engine.queue.redis.queue import RedisQueue
from upnext.sdk.context import Context


class _RecordingCommandQueue:
    def __init__(self) -> None:
        self.items: list[object] = []

    def put(self, item, block: bool = True, timeout: float | None = None) -> None:  # noqa: ANN001
        _ = (block, timeout)
        self.items.append(item)


@pytest.mark.performance
def test_perf_context_progress_coalescing_reduces_command_volume() -> None:
    command_queue = _RecordingCommandQueue()
    ctx = Context(
        job_id="perf-progress-job",
        job_key="perf-progress-key",
        root_id="perf-progress-job",
        _cmd_queue=command_queue,
    )

    total_updates = 1_000
    start = perf_counter()
    for idx in range(total_updates):
        ctx.set_progress(idx / total_updates)
    ctx.set_progress(1.0)
    elapsed = max(perf_counter() - start, 1e-9)

    emitted = len(command_queue.items)
    reduction_ratio = 1 - (emitted / (total_updates + 1))
    updates_per_second = total_updates / elapsed
    print(
        f"context_progress_perf emitted={emitted} total={total_updates + 1} "
        f"reduction_ratio={reduction_ratio:.3f} updates_per_second={updates_per_second:.1f}"
    )

    assert emitted < (total_updates + 1)
    assert emitted > 0


@pytest.mark.performance
@pytest.mark.asyncio
async def test_perf_queue_progress_workload_reports_write_amplification(
    fake_redis,
    monkeypatch,
) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-perf-progress")
    job = Job(
        function="fn.perf.progress",
        function_name="perf_progress",
        kwargs={},
    )
    await queue.enqueue(job)

    get_total = 0
    get_result_key = 0
    setex_total = 0
    original_get = fake_redis.get
    original_setex = fake_redis.setex

    async def tracked_get(key, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        nonlocal get_total, get_result_key
        get_total += 1
        key_str = key.decode() if isinstance(key, bytes) else str(key)
        if ":result:" in key_str:
            get_result_key += 1
        return await original_get(key, *args, **kwargs)

    async def tracked_setex(key, ttl, value):  # noqa: ANN001
        nonlocal setex_total
        setex_total += 1
        return await original_setex(key, ttl, value)

    monkeypatch.setattr(fake_redis, "get", tracked_get)
    monkeypatch.setattr(fake_redis, "setex", tracked_setex)

    total_updates = 250
    start = perf_counter()
    for idx in range(total_updates):
        await queue.update_progress(job.id, (idx + 1) / total_updates)
    elapsed = max(perf_counter() - start, 1e-9)

    updates_per_second = total_updates / elapsed
    print(
        f"queue_progress_perf updates={total_updates} elapsed_s={elapsed:.3f} "
        f"updates_per_second={updates_per_second:.1f} get_total={get_total} "
        f"setex_total={setex_total} result_get={get_result_key}"
    )

    assert get_result_key == 0
    assert updates_per_second > 0
    await queue.close()
