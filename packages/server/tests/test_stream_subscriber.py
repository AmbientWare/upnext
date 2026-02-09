from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import server.services.stream_subscriber as stream_subscriber_module
from server.services.stream_subscriber import StreamSubscriber, StreamSubscriberConfig


@pytest.mark.asyncio
async def test_process_batch_acks_only_successful_events(fake_redis, monkeypatch) -> None:
    config = StreamSubscriberConfig(
        stream="conduit:status:events",
        group="test-group",
        consumer_id="consumer-1",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    call_log: list[str] = []

    async def fake_process_event(event_type: str, data: dict, worker_id: str | None) -> bool:
        call_log.append(event_type)
        if event_type == "job.failed":
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr(stream_subscriber_module, "process_event", fake_process_event)

    ts = datetime.now(UTC).isoformat()
    await fake_redis.xadd(
        config.stream,
        {
            "type": "job.started",
            "job_id": "job-ack-1",
            "worker_id": "worker-1",
            "data": json.dumps(
                {
                    "function": "task_key",
                    "function_name": "task_name",
                    "root_id": "job-ack-1",
                    "attempt": 1,
                    "max_retries": 0,
                    "started_at": ts,
                }
            ),
        },
    )
    await fake_redis.xadd(
        config.stream,
        {
            "type": "job.failed",
            "job_id": "job-ack-2",
            "worker_id": "worker-1",
            "data": json.dumps(
                {
                    "function": "task_key",
                    "function_name": "task_name",
                    "root_id": "job-ack-2",
                    "error": "oops",
                    "attempt": 1,
                    "max_retries": 0,
                    "failed_at": ts,
                }
            ),
        },
    )

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 1
    assert call_log == ["job.started", "job.failed"]

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    assert pending_summary["pending"] == 1


@pytest.mark.asyncio
async def test_process_batch_orders_mixed_fresh_and_reclaimed_events(fake_redis, monkeypatch) -> None:
    config = StreamSubscriberConfig(
        stream="conduit:status:events",
        group="test-order",
        consumer_id="consumer-a",
        batch_size=10,
        poll_interval=0.01,
        stale_claim_ms=0,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    processed_ids: list[str] = []

    async def fake_process_event(event_type: str, data: dict, worker_id: str | None) -> bool:
        processed_ids.append(data["job_id"])
        return True

    monkeypatch.setattr(stream_subscriber_module, "process_event", fake_process_event)

    ts = datetime.now(UTC).isoformat()
    old_id = await fake_redis.xadd(
        config.stream,
        {
            "type": "job.started",
            "job_id": "job-old",
            "worker_id": "worker-1",
            "data": json.dumps(
                {
                    "function": "task_key",
                    "function_name": "task_name",
                    "root_id": "job-old",
                    "attempt": 1,
                    "max_retries": 0,
                    "started_at": ts,
                }
            ),
        },
    )

    # Another consumer reads old event first so it becomes reclaimable pending.
    await fake_redis.xreadgroup(
        config.group,
        "other-consumer",
        {config.stream: ">"},
        count=1,
        block=0,
    )

    new_id = await fake_redis.xadd(
        config.stream,
        {
            "type": "job.started",
            "job_id": "job-new",
            "worker_id": "worker-1",
            "data": json.dumps(
                {
                    "function": "task_key",
                    "function_name": "task_name",
                    "root_id": "job-new",
                    "attempt": 1,
                    "max_retries": 0,
                    "started_at": ts,
                }
            ),
        },
    )

    assert old_id != new_id

    processed = await subscriber._process_batch(drain=False)  # noqa: SLF001
    assert processed == 2
    assert processed_ids == ["job-old", "job-new"]


@pytest.mark.asyncio
async def test_publish_event_filters_sensitive_fields(fake_redis) -> None:
    config = StreamSubscriberConfig(
        stream="conduit:status:events",
        group="test-sse",
        consumer_id="consumer-sse",
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)

    published: dict[str, str] = {}

    async def fake_publish(channel: str, payload: str) -> None:
        published["channel"] = channel
        published["payload"] = payload

    subscriber._redis.publish = fake_publish  # type: ignore[method-assign]  # noqa: SLF001

    await subscriber._publish_event(  # noqa: SLF001
        "job.failed",
        {
            "job_id": "job-safe-1",
            "function": "task_key",
            "function_name": "task_name",
            "root_id": "job-safe-1",
            "error": "failed",
            "attempt": 1,
            "max_retries": 0,
            "failed_at": datetime.now(UTC).isoformat(),
            "kwargs": {"secret": "value"},
            "traceback": "sensitive traceback",
            "state": {"token": "nope"},
        },
        "worker-1",
    )

    assert published["channel"] == "conduit:status:events:pubsub"
    body = json.loads(published["payload"])
    assert body["job_id"] == "job-safe-1"
    assert "kwargs" not in body
    assert "traceback" not in body
    assert "state" not in body


@pytest.mark.asyncio
async def test_reclaim_of_stale_pending_event_processes_once_and_acks(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream="conduit:status:events",
        group="test-reclaim-race",
        consumer_id="consumer-b",
        batch_size=10,
        poll_interval=0.01,
        stale_claim_ms=0,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    call_count = 0

    async def fake_process_event(
        event_type: str, data: dict, worker_id: str | None
    ) -> bool:
        nonlocal call_count
        call_count += 1
        return True

    monkeypatch.setattr(stream_subscriber_module, "process_event", fake_process_event)

    ts = datetime.now(UTC).isoformat()
    event_id = await fake_redis.xadd(
        config.stream,
        {
            "type": "job.completed",
            "job_id": "job-race-1",
            "worker_id": "worker-1",
            "data": json.dumps(
                {
                    "function": "task_key",
                    "function_name": "task_name",
                    "root_id": "job-race-1",
                    "attempt": 1,
                    "completed_at": ts,
                    "duration_ms": 10,
                }
            ),
        },
    )

    # Simulate a crashed consumer that read but never ACKed.
    await fake_redis.xreadgroup(
        config.group,
        "consumer-crashed",
        {config.stream: ">"},
        count=1,
        block=0,
    )

    processed = await subscriber._process_batch(drain=False)  # noqa: SLF001
    assert processed == 1
    assert call_count == 1

    processed_again = await subscriber._process_batch(drain=False)  # noqa: SLF001
    assert processed_again == 0
    assert call_count == 1

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    assert pending_summary["pending"] == 0

    # Sanity: stream still has original event, but it was consumed exactly once.
    rows = await fake_redis.xrange(config.stream, min=event_id, max=event_id)
    assert len(rows) == 1


class _GroupCreateRedisStub:
    def __init__(self, error: Exception | None) -> None:
        self._error = error

    async def xgroup_create(
        self,
        stream: str,  # noqa: ARG002
        group: str,  # noqa: ARG002
        id: str = "0",  # noqa: A002, ARG002
        mkstream: bool = True,  # noqa: FBT001, FBT002, ARG002
    ) -> None:
        if self._error is not None:
            raise self._error


@pytest.mark.asyncio
async def test_ensure_consumer_group_handles_busygroup_and_errors() -> None:
    busy = StreamSubscriber(
        redis_client=_GroupCreateRedisStub(RuntimeError("BUSYGROUP already exists")),
        config=StreamSubscriberConfig(group="group-a", consumer_id="consumer-a"),
    )
    assert await busy._ensure_consumer_group() is True  # noqa: SLF001

    broken = StreamSubscriber(
        redis_client=_GroupCreateRedisStub(RuntimeError("redis unavailable")),
        config=StreamSubscriberConfig(group="group-b", consumer_id="consumer-b"),
    )
    assert await broken._ensure_consumer_group() is False  # noqa: SLF001


@pytest.mark.asyncio
async def test_subscribe_loop_retries_then_drains_on_shutdown(monkeypatch) -> None:
    subscriber = StreamSubscriber(
        redis_client=object(),
        config=StreamSubscriberConfig(
            stream="conduit:status:events",
            group="test-loop",
            consumer_id="consumer-loop",
            poll_interval=0.01,
        ),
    )

    calls: list[bool] = []
    backoff_sleeps: list[float] = []

    async def fake_process_batch(drain: bool = False) -> int:
        calls.append(drain)
        if len(calls) == 1:
            raise RuntimeError("temporary error")
        if drain:
            return 0
        subscriber._stop_event.set()  # noqa: SLF001
        return 0

    async def fake_sleep(delay: float) -> None:
        backoff_sleeps.append(delay)

    monkeypatch.setattr(subscriber, "_process_batch", fake_process_batch)
    monkeypatch.setattr(stream_subscriber_module.asyncio, "sleep", fake_sleep)

    await subscriber._subscribe_loop()  # noqa: SLF001

    assert backoff_sleeps == [2.0]
    assert calls[0] is False
    assert calls[-1] is True


@pytest.mark.asyncio
async def test_process_batch_returns_processed_when_ack_fails(fake_redis, monkeypatch) -> None:
    config = StreamSubscriberConfig(
        stream="conduit:status:events",
        group="test-ack-failure",
        consumer_id="consumer-ack",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    async def fake_process_event(event_type: str, data: dict, worker_id: str | None) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr(stream_subscriber_module, "process_event", fake_process_event)

    await fake_redis.xadd(
        config.stream,
        {
            "type": "job.started",
            "job_id": "job-ack-fail-1",
            "worker_id": "worker-1",
            "data": json.dumps(
                {
                    "function": "task_key",
                    "function_name": "task_name",
                    "root_id": "job-ack-fail-1",
                    "attempt": 1,
                    "max_retries": 0,
                    "started_at": datetime.now(UTC).isoformat(),
                }
            ),
        },
    )

    async def fail_ack(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("ack failed")

    subscriber._redis.xack = fail_ack  # type: ignore[method-assign]  # noqa: SLF001

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 1

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    assert pending_summary["pending"] == 1


@pytest.mark.asyncio
async def test_process_batch_coalesces_duplicate_progress_events(fake_redis, monkeypatch) -> None:
    config = StreamSubscriberConfig(
        stream="conduit:status:events",
        group="test-progress-coalesce",
        consumer_id="consumer-progress",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    seen_progress: list[float] = []

    async def fake_process_event(event_type: str, data: dict, worker_id: str | None) -> bool:  # noqa: ARG001
        if event_type == "job.progress":
            seen_progress.append(float(data.get("progress", 0)))
        return True

    monkeypatch.setattr(stream_subscriber_module, "process_event", fake_process_event)

    ts = datetime.now(UTC).isoformat()
    for progress in (0.1, 0.2, 0.3):
        await fake_redis.xadd(
            config.stream,
            {
                "type": "job.progress",
                "job_id": "job-coalesce-1",
                "worker_id": "worker-1",
                "data": json.dumps(
                    {
                        "root_id": "job-coalesce-1",
                        "progress": progress,
                        "updated_at": ts,
                    }
                ),
            },
        )

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 1
    assert seen_progress == [0.3]

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    assert pending_summary["pending"] == 0
