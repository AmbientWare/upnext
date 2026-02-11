from __future__ import annotations

from datetime import UTC, datetime

import pytest
from server.db.models import JobHistory
from server.services.stream_subscriber import StreamSubscriber, StreamSubscriberConfig
from shared.events import EVENTS_STREAM
from upnext.engine.status import StatusPublisher


@pytest.mark.asyncio
async def test_worker_events_round_trip_to_database_via_stream_subscriber(
    sqlite_db, fake_redis
) -> None:
    publisher = StatusPublisher(fake_redis, worker_id="worker-e2e")
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-e2e-roundtrip",
        consumer_id="consumer-e2e",
        batch_size=10,
        poll_interval=0.01,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    job_id = "roundtrip-job-1"
    await publisher.record_job_started(
        job_id=job_id,
        function="task_key",
        function_name="task_name",
        attempt=1,
        max_retries=0,
        root_id=job_id,
    )
    await publisher.record_job_completed(
        job_id=job_id,
        function="task_key",
        function_name="task_name",
        root_id=job_id,
        attempt=1,
        result={"ok": True},
        duration_ms=12.5,
    )

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 2

    pending = await fake_redis.xpending(config.stream, config.group)
    assert pending["pending"] == 0

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, job_id)
        assert row is not None
        assert row.status == "complete"
        assert row.function == "task_key"
        assert row.function_name == "task_name"
        assert row.worker_id == "worker-e2e"
        assert row.progress == pytest.approx(1.0)
        assert row.completed_at is not None


@pytest.mark.asyncio
async def test_stale_pending_worker_event_is_reclaimed_and_persisted_once(
    sqlite_db, fake_redis
) -> None:
    publisher = StatusPublisher(fake_redis, worker_id="worker-reclaim")
    config = StreamSubscriberConfig(
        stream=EVENTS_STREAM,
        group="test-e2e-reclaim",
        consumer_id="consumer-reclaim",
        batch_size=10,
        poll_interval=0.01,
        stale_claim_ms=0,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    job_id = "reclaim-job-1"
    await publisher.record_job_started(
        job_id=job_id,
        function="task_key",
        function_name="task_name",
        attempt=1,
        max_retries=0,
        root_id=job_id,
        metadata={"created": datetime.now(UTC).isoformat()},
    )

    # Simulate a crashed consumer that read but did not ACK.
    await fake_redis.xreadgroup(
        config.group,
        "consumer-crashed",
        {config.stream: ">"},
        count=1,
        block=0,
    )

    processed = await subscriber._process_batch(drain=False)  # noqa: SLF001
    assert processed == 1
    processed_again = await subscriber._process_batch(drain=False)  # noqa: SLF001
    assert processed_again == 0

    pending = await fake_redis.xpending(config.stream, config.group)
    assert pending["pending"] == 0

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, job_id)
        assert row is not None
        assert row.status == "active"
        assert row.attempts == 1
