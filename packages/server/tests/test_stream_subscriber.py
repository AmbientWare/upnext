from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import server.services.events.subscriber as stream_subscriber_module
from server.services.events import StreamSubscriber, StreamSubscriberConfig
from shared.contracts import (
    JobCancelledEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobStartedEvent,
)
from shared.keys import EVENTS_PUBSUB_CHANNEL, EVENTS_STREAM


@pytest.mark.asyncio
async def test_process_batch_acks_only_successful_events(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-group",
        consumer_id="consumer-1",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    call_log: list[str] = []

    async def fake_process_event(event: object) -> bool:
        call_log.append(type(event).__name__)
        if isinstance(event, JobFailedEvent):
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
                    "job_key": "job-ack-1",
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
    assert call_log == ["JobStartedEvent", "JobFailedEvent"]

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    assert pending_summary["pending"] == 1


@pytest.mark.asyncio
async def test_process_batch_orders_mixed_fresh_and_reclaimed_events(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-order",
        consumer_id="consumer-a",
        batch_size=10,
        poll_interval=0.01,
        stale_claim_ms=0,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    processed_ids: list[str] = []

    async def fake_process_event(event: object) -> bool:
        processed_ids.append(str(getattr(event, "job_id")))
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
                    "job_key": "job-old",
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
                    "job_key": "job-new",
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
        stream=EVENTS_STREAM,
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

    assert published["channel"] == EVENTS_PUBSUB_CHANNEL
    body = json.loads(published["payload"])
    assert body["job_id"] == "job-safe-1"
    assert "kwargs" not in body
    assert "traceback" not in body
    assert "state" not in body


def test_parse_events_propagates_worker_id_for_started_events(fake_redis) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-started-worker-id",
        consumer_id="consumer-started",
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)

    ts = datetime.now(UTC).isoformat()
    events = [
        (
            "1-0",
            {
                "type": "job.started",
                "job_id": "job-started-worker-1",
                "worker_id": "worker-123",
                "data": json.dumps(
                    {
                        "function": "task_key",
                        "function_name": "task_name",
                        "root_id": "job-started-worker-1",
                        "job_key": "job-started-worker-1",
                        "attempt": 1,
                        "max_retries": 0,
                        "started_at": ts,
                    }
                ),
            },
        )
    ]

    parsed, summary = subscriber._parse_events(events)  # noqa: SLF001
    assert summary.total == 0
    assert len(parsed) == 1
    assert isinstance(parsed[0].event, JobStartedEvent)
    assert parsed[0].event.worker_id == "worker-123"


def test_parse_events_supports_job_cancelled(fake_redis) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-cancelled-event",
        consumer_id="consumer-cancelled",
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)

    ts = datetime.now(UTC).isoformat()
    events = [
        (
            "1-0",
            {
                "type": "job.cancelled",
                "job_id": "job-cancelled-1",
                "worker_id": "worker-123",
                "data": json.dumps(
                    {
                        "function": "task_key",
                        "function_name": "task_name",
                        "root_id": "job-cancelled-1",
                        "attempt": 1,
                        "reason": "cancelled",
                        "cancelled_at": ts,
                    }
                ),
            },
        )
    ]

    parsed, summary = subscriber._parse_events(events)  # noqa: SLF001
    assert summary.total == 0
    assert len(parsed) == 1
    assert isinstance(parsed[0].event, JobCancelledEvent)


@pytest.mark.asyncio
async def test_invalid_events_are_archived_before_ack(fake_redis) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-invalid-archive",
        consumer_id="consumer-invalid",
        invalid_events_stream=f"{EVENTS_STREAM}:invalid:test",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    await fake_redis.xadd(
        config.stream,
        {
            "type": "job.not-real",
            "job_id": "job-invalid-1",
            "worker_id": "worker-1",
            "data": "{}",
        },
    )

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 0

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    assert pending_summary["pending"] == 0

    invalid_rows = await fake_redis.xrange(config.invalid_events_stream, count=10)
    assert len(invalid_rows) == 1
    payload = invalid_rows[0][1]
    assert payload[b"event_id"]
    assert payload[b"reason"] == b"invalid_envelope"


@pytest.mark.asyncio
async def test_invalid_events_stay_pending_when_archive_write_fails(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-invalid-archive-fail",
        consumer_id="consumer-invalid-fail",
        invalid_events_stream=f"{EVENTS_STREAM}:invalid:fail",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    await fake_redis.xadd(
        config.stream,
        {
            "type": "job.not-real",
            "job_id": "job-invalid-2",
            "worker_id": "worker-1",
            "data": "{}",
        },
    )

    original_xadd = fake_redis.xadd

    async def fail_invalid_stream_xadd(*args, **kwargs):  # noqa: ANN002, ANN003
        if args and args[0] == config.invalid_events_stream:
            raise RuntimeError("invalid stream down")
        return await original_xadd(*args, **kwargs)

    monkeypatch.setattr(fake_redis, "xadd", fail_invalid_stream_xadd)

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 0

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    assert pending_summary["pending"] == 1
    invalid_rows = await fake_redis.xrange(config.invalid_events_stream, count=10)
    assert invalid_rows == []


@pytest.mark.asyncio
async def test_reclaim_of_stale_pending_event_processes_once_and_acks(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-reclaim-race",
        consumer_id="consumer-b",
        batch_size=10,
        poll_interval=0.01,
        stale_claim_ms=0,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    call_count = 0

    async def fake_process_event(event: object) -> bool:  # noqa: ARG001
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
            stream=EVENTS_STREAM,
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
async def test_subscribe_loop_skips_idle_wait_when_events_were_processed(
    monkeypatch,
) -> None:
    subscriber = StreamSubscriber(
        redis_client=object(),
        config=StreamSubscriberConfig(
            stream=EVENTS_STREAM,
            group="test-loop-drain",
            consumer_id="consumer-loop-drain",
            poll_interval=1.0,
        ),
    )

    calls = 0
    wait_timeouts: list[float] = []
    original_wait_for = stream_subscriber_module.asyncio.wait_for

    async def fake_process_batch(drain: bool = False) -> int:
        nonlocal calls
        if drain:
            return 0
        calls += 1
        if calls == 1:
            return 1
        subscriber._stop_event.set()  # noqa: SLF001
        return 0

    async def fake_wait_for(awaitable, timeout):  # type: ignore[no-untyped-def]
        wait_timeouts.append(float(timeout))
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr(subscriber, "_process_batch", fake_process_batch)
    monkeypatch.setattr(stream_subscriber_module.asyncio, "wait_for", fake_wait_for)

    await subscriber._subscribe_loop()  # noqa: SLF001

    # Only the idle iteration should wait; processed iteration should continue immediately.
    assert len(wait_timeouts) == 1
    assert wait_timeouts[0] == pytest.approx(0.25, rel=0, abs=1e-6)


@pytest.mark.asyncio
async def test_process_batch_returns_processed_when_ack_fails(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-ack-failure",
        consumer_id="consumer-ack",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    async def fake_process_event(event: object) -> bool:  # noqa: ARG001
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
                    "job_key": "job-ack-fail-1",
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
async def test_process_batch_coalesces_duplicate_progress_events(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-progress-coalesce",
        consumer_id="consumer-progress",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    seen_progress: list[float] = []

    async def fake_process_event(event: object) -> bool:  # noqa: ARG001
        if isinstance(event, JobProgressEvent):
            seen_progress.append(float(getattr(event, "progress", 0)))
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


@pytest.mark.asyncio
async def test_coalesced_progress_events_are_not_acked_when_latest_fails(
    fake_redis, monkeypatch
) -> None:
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-progress-failure",
        consumer_id="consumer-progress-failure",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    async def fake_process_event(event: object) -> bool:  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(stream_subscriber_module, "process_event", fake_process_event)

    ts = datetime.now(UTC).isoformat()
    for progress in (0.1, 0.2):
        await fake_redis.xadd(
            config.stream,
            {
                "type": "job.progress",
                "job_id": "job-coalesce-fail-1",
                "worker_id": "worker-1",
                "data": json.dumps(
                    {
                        "root_id": "job-coalesce-fail-1",
                        "progress": progress,
                        "updated_at": ts,
                    }
                ),
            },
        )

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 0

    pending_summary = await fake_redis.xpending(config.stream, config.group)
    # Both events should remain pending for replay when the failure clears.
    assert pending_summary["pending"] == 2
