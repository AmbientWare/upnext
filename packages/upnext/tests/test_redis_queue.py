from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

import pytest
from shared.models import Job, JobStatus
from shared.schemas import FunctionConfig, FunctionType, MissedRunPolicy
from shared.workers import FUNCTION_KEY_PREFIX
from upnext.engine.queue.base import DuplicateJobError
from upnext.engine.queue.redis.queue import RedisQueue


@pytest.fixture
def queue(fake_redis):
    return RedisQueue(client=fake_redis, claim_timeout_ms=50, key_prefix="upnext-test")


@pytest.mark.asyncio
async def test_enqueue_duplicate_job_key_raises(queue: RedisQueue) -> None:
    job1 = Job(function="task_fn", function_name="task", key="dup-key")
    job2 = Job(function="task_fn", function_name="task", key="dup-key")

    await queue.enqueue(job1)
    with pytest.raises(DuplicateJobError):
        await queue.enqueue(job2)


@pytest.mark.asyncio
async def test_queue_lifecycle_enqueue_dequeue_finish_cleans_keys(
    queue: RedisQueue,
) -> None:
    job = Job(function="task_fn", function_name="task", key="job-key-1")
    await queue.enqueue(job)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    assert active.id == job.id

    await queue.finish(active, JobStatus.COMPLETE, result={"ok": True})

    client = await queue._ensure_connected()  # noqa: SLF001
    result_data = await client.get(queue._result_key(job.id))  # noqa: SLF001
    job_data = await client.get(queue._job_key(job))  # noqa: SLF001
    index_data = await client.get(queue._job_index_key(job.id))  # noqa: SLF001
    dedup_exists = await client.sismember(queue._dedup_key(job.function), job.key)  # noqa: SLF001

    assert result_data is not None
    assert job_data is None
    assert index_data is None
    assert dedup_exists == 0


@pytest.mark.asyncio
async def test_retry_clears_stream_metadata_and_requeues_immediately(
    queue: RedisQueue,
) -> None:
    job = Job(function="task_fn", function_name="task", key="retry-key")
    await queue.enqueue(job)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    old_msg_id = active.metadata.get("_stream_msg_id")

    await queue.retry(active, delay=0)

    # Retry should clear stream metadata from the job payload and put it back on stream.
    requeued = await queue.dequeue(["task_fn"], timeout=0.2)
    assert requeued is not None
    assert requeued.id == active.id
    assert requeued.metadata.get("_stream_msg_id") != old_msg_id


@pytest.mark.asyncio
async def test_retry_with_delay_goes_to_scheduled_set(queue: RedisQueue) -> None:
    job = Job(function="task_fn", function_name="task", key="retry-delay-key")
    await queue.enqueue(job)
    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None

    await queue.retry(active, delay=10)

    client = await queue._ensure_connected()  # noqa: SLF001
    scheduled_score = await client.zscore(queue._scheduled_key(job.function), job.id)  # noqa: SLF001
    assert scheduled_score is not None


@pytest.mark.asyncio
async def test_cancel_non_terminal_job_returns_true(queue: RedisQueue) -> None:
    queued_job = Job(function="task_fn", function_name="task", key="cancel-key")
    await queue.enqueue(queued_job)

    assert await queue.cancel(queued_job.id) is True
    cancelled = await queue.get_job(queued_job.id)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED

    # Cancellation should prevent queued jobs from executing.
    candidate = await queue.dequeue(["task_fn"], timeout=0.05)
    assert candidate is None

    # Cancel should release the dedup key so callers can re-submit immediately.
    client = await queue._ensure_connected()  # noqa: SLF001
    assert await client.sismember(queue._dedup_key(queued_job.function), queued_job.key) == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_cancel_terminal_job_returns_false(queue: RedisQueue) -> None:
    terminal_job = Job(function="task_fn", function_name="task", key="terminal-key")
    await queue.enqueue(terminal_job)
    active = None
    for _ in range(4):
        candidate = await queue.dequeue(["task_fn"], timeout=0.2)
        if candidate is None:
            continue
        if candidate.id == terminal_job.id:
            active = candidate
            break
    assert active is not None
    await queue.finish(active, JobStatus.COMPLETE)

    assert await queue.cancel(terminal_job.id) is False


@pytest.mark.asyncio
async def test_dequeue_skips_paused_function_until_resumed(queue: RedisQueue) -> None:
    job = Job(function="task_fn", function_name="task", key="paused-key")
    await queue.enqueue(job)

    client = await queue._ensure_connected()  # noqa: SLF001
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:task_fn",
        b'{"key":"task_fn","name":"task_fn","paused":true}',
    )

    paused_pick = await queue.dequeue(["task_fn"], timeout=0.05)
    assert paused_pick is None

    await client.set(
        f"{FUNCTION_KEY_PREFIX}:task_fn",
        b'{"key":"task_fn","name":"task_fn","paused":false}',
    )
    queue._function_pause_cache.clear()  # noqa: SLF001

    resumed_pick = await queue.dequeue(["task_fn"], timeout=0.2)
    assert resumed_pick is not None
    assert resumed_pick.id == job.id


@pytest.mark.asyncio
async def test_xautoclaim_recovers_stale_message(fake_redis) -> None:
    q1 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-claim")
    q2 = RedisQueue(client=fake_redis, claim_timeout_ms=20, key_prefix="upnext-claim")

    job = Job(function="task_fn", function_name="task", key="claim-key")
    await q1.enqueue(job)

    first = await q1.dequeue(["task_fn"], timeout=0.2)
    assert first is not None

    deadline = time.monotonic() + 1.0
    recovered = None
    while time.monotonic() < deadline:
        recovered = await q2.dequeue(["task_fn"], timeout=0.05)
        if recovered is not None:
            break
        await asyncio.sleep(0.01)

    assert recovered is not None
    assert recovered.id == job.id


@pytest.mark.asyncio
async def test_heartbeat_prevents_reclaim(fake_redis) -> None:
    q1 = RedisQueue(
        client=fake_redis, claim_timeout_ms=200, key_prefix="upnext-heartbeat"
    )
    q2 = RedisQueue(
        client=fake_redis, claim_timeout_ms=200, key_prefix="upnext-heartbeat"
    )

    job = Job(function="task_fn", function_name="task", key="heartbeat-key")
    await q1.enqueue(job)

    first = await q1.dequeue(["task_fn"], timeout=0.2)
    assert first is not None

    await asyncio.sleep(0.05)
    await q1.heartbeat_active_jobs([first])
    await asyncio.sleep(0.05)

    for _ in range(3):
        reclaimed = await q2.dequeue(["task_fn"], timeout=0.02)
        assert reclaimed is None


@pytest.mark.asyncio
async def test_default_stream_maxlen_does_not_trim_unconsumed_jobs(queue: RedisQueue) -> None:
    total = 12
    submitted: list[str] = []
    for idx in range(total):
        job = Job(function="task_fn", function_name="task", key=f"no-trim-{idx}")
        submitted.append(job.id)
        await queue.enqueue(job)

    seen: list[str] = []
    for _ in range(total):
        job = await queue.dequeue(["task_fn"], timeout=0.2)
        assert job is not None
        seen.append(job.id)

    assert seen == submitted


@pytest.mark.asyncio
async def test_failed_job_moves_to_dead_letter_and_can_be_replayed(
    queue: RedisQueue,
) -> None:
    job = Job(function="task_fn", function_name="task", key="dlq-key-1")
    await queue.enqueue(job)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    await queue.finish(active, JobStatus.FAILED, error="poison payload")

    dead_letters = await queue.get_dead_letters("task_fn", limit=10)
    assert len(dead_letters) == 1
    entry = dead_letters[0]
    assert entry.job.id == job.id
    assert entry.reason == "poison payload"

    replayed_job_id = await queue.replay_dead_letter("task_fn", entry.entry_id)
    assert replayed_job_id is not None
    assert replayed_job_id != job.id

    replayed = await queue.dequeue(["task_fn"], timeout=0.2)
    assert replayed is not None
    assert replayed.id == replayed_job_id
    assert replayed.metadata.get("dlq_replayed_from") == entry.entry_id

    assert await queue.get_dead_letters("task_fn", limit=10) == []


@pytest.mark.asyncio
async def test_replay_dead_letter_rejects_duplicate_active_key(queue: RedisQueue) -> None:
    first = Job(function="task_fn", function_name="task", key="dlq-dup-key")
    await queue.enqueue(first)
    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    await queue.finish(active, JobStatus.FAILED, error="failed")

    entry = (await queue.get_dead_letters("task_fn", limit=1))[0]

    blocking = Job(function="task_fn", function_name="task", key="dlq-dup-key")
    await queue.enqueue(blocking)

    with pytest.raises(DuplicateJobError):
        await queue.replay_dead_letter("task_fn", entry.entry_id)

    # Replay failed and entry should remain for future manual handling.
    remaining = await queue.get_dead_letters("task_fn", limit=10)
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_rate_limit_blocks_dispatch_and_requeues_for_later(queue: RedisQueue) -> None:
    client = await queue._ensure_connected()  # noqa: SLF001
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:task_fn",
        b'{"key":"task_fn","name":"task_fn","paused":false,"rate_limit":"1/h"}',
    )

    first = Job(function="task_fn", function_name="task", key="rate-limit-1")
    second = Job(function="task_fn", function_name="task", key="rate-limit-2")
    await queue.enqueue(first)
    await queue.enqueue(second)

    run_first = await queue.dequeue(["task_fn"], timeout=0.2)
    assert run_first is not None
    assert run_first.id == first.id
    await queue.finish(run_first, JobStatus.COMPLETE)

    # Second dequeue is rate-limited and job is rescheduled for later.
    run_second = await queue.dequeue(["task_fn"], timeout=0.2)
    assert run_second is None

    scheduled_at = await client.zscore(queue._scheduled_key("task_fn"), second.id)  # noqa: SLF001
    assert scheduled_at is not None


@pytest.mark.asyncio
async def test_max_concurrency_blocks_excess_dispatch(queue: RedisQueue) -> None:
    client = await queue._ensure_connected()  # noqa: SLF001
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:task_fn",
        b'{"key":"task_fn","name":"task_fn","paused":false,"max_concurrency":1}',
    )

    first = Job(function="task_fn", function_name="task", key="max-concurrency-1")
    second = Job(function="task_fn", function_name="task", key="max-concurrency-2")
    await queue.enqueue(first)
    await queue.enqueue(second)

    run_first = await queue.dequeue(["task_fn"], timeout=0.2)
    assert run_first is not None
    assert run_first.id == first.id

    run_second = await queue.dequeue(["task_fn"], timeout=0.2)
    assert run_second is None

    scheduled_at = await client.zscore(queue._scheduled_key("task_fn"), second.id)  # noqa: SLF001
    assert scheduled_at is None

    await queue.finish(run_first, JobStatus.COMPLETE)
    unblocked = await queue.dequeue(["task_fn"], timeout=0.2)
    assert unblocked is not None
    assert unblocked.id == second.id


@pytest.mark.asyncio
async def test_dequeue_round_robin_prevents_hot_stream_starvation(queue: RedisQueue) -> None:
    hot = Job(function="hot_fn", function_name="hot", key="hot-1")
    cold = Job(function="cold_fn", function_name="cold", key="cold-1")
    await queue.enqueue(hot)
    await queue.enqueue(cold)

    first = await queue.dequeue(["hot_fn", "cold_fn"], timeout=0.2)
    assert first is not None
    await queue.finish(first, JobStatus.COMPLETE)

    second = await queue.dequeue(["hot_fn", "cold_fn"], timeout=0.2)
    assert second is not None

    assert {first.function, second.function} == {"hot_fn", "cold_fn"}


@pytest.mark.asyncio
async def test_group_concurrency_cap_limits_shared_routing_group(
    queue: RedisQueue,
) -> None:
    client = await queue._ensure_connected()  # noqa: SLF001
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:fn.group.a",
        b'{"key":"fn.group.a","name":"group_a","paused":false,"routing_group":"tenant-a","group_max_concurrency":1}',
    )
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:fn.group.b",
        b'{"key":"fn.group.b","name":"group_b","paused":false,"routing_group":"tenant-a","group_max_concurrency":1}',
    )

    a = Job(function="fn.group.a", function_name="group_a", key="group-a")
    b = Job(function="fn.group.b", function_name="group_b", key="group-b")
    await queue.enqueue(a)
    await queue.enqueue(b)

    first = await queue.dequeue(["fn.group.a", "fn.group.b"], timeout=0.2)
    assert first is not None

    second = await queue.dequeue(["fn.group.a", "fn.group.b"], timeout=0.2)
    assert second is None

    await queue.finish(first, JobStatus.COMPLETE)
    next_job = await queue.dequeue(["fn.group.a", "fn.group.b"], timeout=0.2)
    assert next_job is not None
    assert {first.id, next_job.id} == {a.id, b.id}


@pytest.mark.asyncio
async def test_cron_cursor_persists_next_and_last_completion(queue: RedisQueue) -> None:
    now = time.time()
    cron_job = Job(
        function="cron.fn",
        function_name="cron_fn",
        key="cron:cron.fn",
        schedule="* * * * *",
        metadata={"cron": True},
    )

    seeded = await queue.seed_cron(cron_job, next_run_at=now + 60)
    assert seeded is True

    client = await queue._ensure_connected()  # noqa: SLF001
    seeded_cursor_raw = await client.hget(queue._cron_cursor_key(), "cron.fn")  # noqa: SLF001
    assert seeded_cursor_raw is not None
    seeded_cursor = json.loads(
        seeded_cursor_raw.decode()
        if isinstance(seeded_cursor_raw, bytes)
        else seeded_cursor_raw
    )
    assert seeded_cursor["function"] == "cron.fn"
    assert seeded_cursor["next_run_at"] is not None
    assert seeded_cursor["last_completed_at"] is None

    cron_job.completed_at = datetime.now(UTC)
    await queue.reschedule_cron(cron_job, next_run_at=now + 120)

    cursor_raw = await client.hget(queue._cron_cursor_key(), "cron.fn")  # noqa: SLF001
    assert cursor_raw is not None
    cursor = json.loads(
        cursor_raw.decode() if isinstance(cursor_raw, bytes) else cursor_raw
    )
    assert cursor["next_run_at"] is not None
    assert cursor["last_completed_at"] is not None


@pytest.mark.asyncio
async def test_reschedule_cron_same_window_reuses_existing_reservation(
    queue: RedisQueue,
) -> None:
    now = time.time()
    client = await queue._ensure_connected()  # noqa: SLF001
    cron_job = Job(
        function="cron.resv",
        function_name="cron_resv",
        key="cron:cron.resv",
        schedule="* * * * *",
        metadata={"cron": True},
    )
    cron_job.completed_at = datetime.now(UTC)
    next_run_at = now + 60

    first_id = await queue.reschedule_cron(cron_job, next_run_at=next_run_at)
    second_id = await queue.reschedule_cron(cron_job, next_run_at=next_run_at)

    assert second_id == first_id
    scheduled = await client.zrange(queue._scheduled_key("cron.resv"), 0, -1)  # noqa: SLF001
    assert len(scheduled) == 1
    assert (
        scheduled[0].decode() if isinstance(scheduled[0], bytes) else str(scheduled[0])
    ) == first_id


@pytest.mark.asyncio
async def test_reschedule_cron_reclaims_stale_window_reservation(
    queue: RedisQueue,
) -> None:
    now = time.time()
    client = await queue._ensure_connected()  # noqa: SLF001
    next_run_at = now + 120
    await client.set(
        queue._cron_window_reservation_key("cron.stale", next_run_at),  # noqa: SLF001
        "stale-job-id",
        ex=3600,
    )

    cron_job = Job(
        function="cron.stale",
        function_name="cron_stale",
        key="cron:cron.stale",
        schedule="* * * * *",
        metadata={"cron": True},
    )
    cron_job.completed_at = datetime.now(UTC)

    job_id = await queue.reschedule_cron(cron_job, next_run_at=next_run_at)
    assert job_id != "stale-job-id"

    job_raw = await client.get(queue._key("job", "cron.stale", job_id))  # noqa: SLF001
    assert job_raw is not None
    score = await client.zscore(queue._scheduled_key("cron.stale"), job_id)  # noqa: SLF001
    assert score is not None


@pytest.mark.asyncio
async def test_cron_startup_reconciliation_enqueues_catchup_when_cursor_is_stale(
    queue: RedisQueue,
) -> None:
    now = time.time()
    client = await queue._ensure_connected()  # noqa: SLF001
    stale_next_run = now - 120

    await client.hset(
        queue._cron_cursor_key(),  # noqa: SLF001
        "cron.reconcile",
        json.dumps(
            {
                "function": "cron.reconcile",
                "next_run_at": datetime.fromtimestamp(stale_next_run, UTC).isoformat(),
                "last_completed_at": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )

    cron_job = Job(
        function="cron.reconcile",
        function_name="cron_reconcile",
        key="cron:cron.reconcile",
        schedule="* * * * *",
        metadata={"cron": True},
    )

    reconciled = await queue.reconcile_cron_startup(cron_job, now_ts=now)
    assert reconciled is True

    cron_job_id_raw = await client.hget(
        queue._cron_registry_key(),  # noqa: SLF001
        "cron:cron.reconcile",
    )
    assert cron_job_id_raw is not None
    cron_job_id = (
        cron_job_id_raw.decode()
        if isinstance(cron_job_id_raw, bytes)
        else str(cron_job_id_raw)
    )

    reconciled_job_raw = await client.get(
        queue._key("job", "cron.reconcile", cron_job_id)  # noqa: SLF001
    )
    assert reconciled_job_raw is not None
    reconciled_job = Job.from_json(
        reconciled_job_raw.decode()
        if isinstance(reconciled_job_raw, bytes)
        else reconciled_job_raw
    )
    assert reconciled_job.metadata.get("startup_reconciled") is True
    assert reconciled_job.metadata.get("startup_policy") == "catch_up"
    reconciled_window = float(reconciled_job.metadata["cron_window_at"])
    assert reconciled_window <= now
    assert reconciled_window >= stale_next_run - 0.001

    cursor_raw = await client.hget(queue._cron_cursor_key(), "cron.reconcile")  # noqa: SLF001
    assert cursor_raw is not None
    cursor = json.loads(
        cursor_raw.decode() if isinstance(cursor_raw, bytes) else cursor_raw
    )
    assert datetime.fromisoformat(cursor["next_run_at"]).timestamp() > reconciled_window


@pytest.mark.asyncio
async def test_cron_startup_reconciliation_latest_only_uses_latest_window(
    queue: RedisQueue,
) -> None:
    now = time.time()
    client = await queue._ensure_connected()  # noqa: SLF001
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:cron.latest",
        FunctionConfig(
            key="cron.latest",
            name="cron_latest",
            type=FunctionType.CRON,
            missed_run_policy=MissedRunPolicy.LATEST_ONLY,
        ).model_dump_json(),
    )
    stale_next_run = now - 360
    await client.hset(
        queue._cron_cursor_key(),  # noqa: SLF001
        "cron.latest",
        json.dumps(
            {
                "function": "cron.latest",
                "next_run_at": datetime.fromtimestamp(stale_next_run, UTC).isoformat(),
                "last_completed_at": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )

    cron_job = Job(
        function="cron.latest",
        function_name="cron_latest",
        key="cron:cron.latest",
        schedule="* * * * *",
        metadata={"cron": True},
    )
    reconciled = await queue.reconcile_cron_startup(cron_job, now_ts=now)
    assert reconciled is True

    cron_job_id_raw = await client.hget(queue._cron_registry_key(), "cron:cron.latest")  # noqa: SLF001
    assert cron_job_id_raw is not None
    cron_job_id = (
        cron_job_id_raw.decode()
        if isinstance(cron_job_id_raw, bytes)
        else str(cron_job_id_raw)
    )
    reconciled_job_raw = await client.get(queue._key("job", "cron.latest", cron_job_id))  # noqa: SLF001
    assert reconciled_job_raw is not None
    reconciled_job = Job.from_json(
        reconciled_job_raw.decode()
        if isinstance(reconciled_job_raw, bytes)
        else reconciled_job_raw
    )
    assert reconciled_job.metadata.get("startup_policy") == "latest_only"
    assert float(reconciled_job.metadata["cron_window_at"]) > stale_next_run + 60


@pytest.mark.asyncio
async def test_cron_startup_reconciliation_skip_policy_advances_cursor_without_enqueue(
    queue: RedisQueue,
) -> None:
    now = time.time()
    client = await queue._ensure_connected()  # noqa: SLF001
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:cron.skip",
        FunctionConfig(
            key="cron.skip",
            name="cron_skip",
            type=FunctionType.CRON,
            missed_run_policy=MissedRunPolicy.SKIP,
        ).model_dump_json(),
    )
    await client.hset(
        queue._cron_cursor_key(),  # noqa: SLF001
        "cron.skip",
        json.dumps(
            {
                "function": "cron.skip",
                "next_run_at": datetime.fromtimestamp(now - 300, UTC).isoformat(),
                "last_completed_at": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )

    cron_job = Job(
        function="cron.skip",
        function_name="cron_skip",
        key="cron:cron.skip",
        schedule="* * * * *",
        metadata={"cron": True},
    )

    reconciled = await queue.reconcile_cron_startup(cron_job, now_ts=now)
    assert reconciled is False

    cron_job_id = await client.hget(queue._cron_registry_key(), "cron:cron.skip")  # noqa: SLF001
    assert cron_job_id is None
    cursor_raw = await client.hget(queue._cron_cursor_key(), "cron.skip")  # noqa: SLF001
    assert cursor_raw is not None
    cursor = json.loads(
        cursor_raw.decode() if isinstance(cursor_raw, bytes) else cursor_raw
    )
    assert datetime.fromisoformat(cursor["next_run_at"]).timestamp() > now


@pytest.mark.asyncio
async def test_cron_startup_reconciliation_catch_up_window_respects_max_seconds(
    queue: RedisQueue,
) -> None:
    now = time.time()
    client = await queue._ensure_connected()  # noqa: SLF001
    await client.set(
        f"{FUNCTION_KEY_PREFIX}:cron.windowed",
        FunctionConfig(
            key="cron.windowed",
            name="cron_windowed",
            type=FunctionType.CRON,
            missed_run_policy=MissedRunPolicy.CATCH_UP,
            max_catch_up_seconds=90,
        ).model_dump_json(),
    )
    stale_next_run = now - 600
    await client.hset(
        queue._cron_cursor_key(),  # noqa: SLF001
        "cron.windowed",
        json.dumps(
            {
                "function": "cron.windowed",
                "next_run_at": datetime.fromtimestamp(stale_next_run, UTC).isoformat(),
                "last_completed_at": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )

    cron_job = Job(
        function="cron.windowed",
        function_name="cron_windowed",
        key="cron:cron.windowed",
        schedule="* * * * *",
        metadata={"cron": True},
    )
    reconciled = await queue.reconcile_cron_startup(cron_job, now_ts=now)
    assert reconciled is True

    cron_job_id_raw = await client.hget(queue._cron_registry_key(), "cron:cron.windowed")  # noqa: SLF001
    assert cron_job_id_raw is not None
    cron_job_id = (
        cron_job_id_raw.decode()
        if isinstance(cron_job_id_raw, bytes)
        else str(cron_job_id_raw)
    )
    reconciled_job_raw = await client.get(
        queue._key("job", "cron.windowed", cron_job_id)  # noqa: SLF001
    )
    assert reconciled_job_raw is not None
    reconciled_job = Job.from_json(
        reconciled_job_raw.decode()
        if isinstance(reconciled_job_raw, bytes)
        else reconciled_job_raw
    )
    assert reconciled_job.metadata.get("startup_policy") == "catch_up"
    assert float(reconciled_job.metadata["cron_window_at"]) >= now - 90
