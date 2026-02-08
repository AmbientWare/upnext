from __future__ import annotations

import os
from typing import Any, cast
from uuid import uuid4

import pytest
import redis.asyncio as redis

from conduit.engine.status import StatusPublisher, StatusPublisherConfig
from server.db.models import JobHistory
from server.db.session import init_database
import server.db.session as session_module
import server.services.event_processing as event_processing_module
from server.services.stream_subscriber import StreamSubscriber, StreamSubscriberConfig

pytestmark = pytest.mark.integration


@pytest.fixture
async def real_infra(monkeypatch):
    redis_url = os.getenv("CONDUIT_TEST_REDIS_URL")
    database_url = os.getenv("CONDUIT_TEST_DATABASE_URL")
    if not redis_url or not database_url:
        pytest.skip(
            "Set CONDUIT_TEST_REDIS_URL and CONDUIT_TEST_DATABASE_URL to run real infra tests."
        )

    redis_client = redis.from_url(redis_url, decode_responses=True)
    await cast(Any, redis_client).ping()

    db = init_database(database_url)
    await db.connect()
    await db.drop_tables()
    await db.create_tables()
    monkeypatch.setattr(event_processing_module, "get_database", lambda: db)

    try:
        yield redis_client, db
    finally:
        await db.drop_tables()
        await db.disconnect()
        session_module._database = None  # type: ignore[attr-defined]
        await redis_client.aclose()


@pytest.mark.asyncio
async def test_real_round_trip_worker_events_persist_to_postgres(real_infra) -> None:
    redis_client, db = real_infra

    suffix = uuid4().hex
    stream = f"conduit:status:events:real:{suffix}"
    group = f"group-{suffix}"
    consumer = f"consumer-{suffix}"
    job_id = suffix

    publisher = StatusPublisher(
        redis_client,
        worker_id="worker-real",
        config=StatusPublisherConfig(stream=stream),
    )
    subscriber = StreamSubscriber(
        redis_client=redis_client,
        config=StreamSubscriberConfig(
            stream=stream,
            group=group,
            consumer_id=consumer,
            batch_size=10,
            poll_interval=0.01,
        ),
    )
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

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
        duration_ms=20.0,
    )

    processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
    assert processed == 2

    pending = await redis_client.xpending(stream, group)
    assert pending["pending"] == 0

    async with db.session() as session:
        row = await session.get(JobHistory, job_id)
        assert row is not None
        assert row.status == "complete"
        assert row.worker_id == "worker-real"
        assert row.result == {"ok": True}


@pytest.mark.asyncio
async def test_real_stale_pending_event_is_reclaimed_after_consumer_crash(
    real_infra,
) -> None:
    redis_client, db = real_infra

    suffix = uuid4().hex
    stream = f"conduit:status:events:real-reclaim:{suffix}"
    group = f"group-{suffix}"
    consumer = f"consumer-{suffix}"
    job_id = suffix

    publisher = StatusPublisher(
        redis_client,
        worker_id="worker-reclaim",
        config=StatusPublisherConfig(stream=stream),
    )
    subscriber = StreamSubscriber(
        redis_client=redis_client,
        config=StreamSubscriberConfig(
            stream=stream,
            group=group,
            consumer_id=consumer,
            batch_size=10,
            poll_interval=0.01,
            stale_claim_ms=0,
        ),
    )
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    await publisher.record_job_started(
        job_id=job_id,
        function="task_key",
        function_name="task_name",
        attempt=1,
        max_retries=0,
        root_id=job_id,
    )

    # Simulate crashed consumer that read but never ACKed.
    await redis_client.xreadgroup(group, f"crashed-{suffix}", {stream: ">"}, count=1, block=0)

    processed = await subscriber._process_batch(drain=False)  # noqa: SLF001
    assert processed == 1
    processed_again = await subscriber._process_batch(drain=False)  # noqa: SLF001
    assert processed_again == 0

    pending = await redis_client.xpending(stream, group)
    assert pending["pending"] == 0

    async with db.session() as session:
        row = await session.get(JobHistory, job_id)
        assert row is not None
        assert row.status == "active"
        assert row.attempts == 1


@pytest.mark.asyncio
async def test_real_consumer_restart_continues_processing_same_group(
    real_infra,
) -> None:
    redis_client, db = real_infra

    suffix = uuid4().hex
    stream = f"conduit:status:events:real-restart:{suffix}"
    group = f"group-{suffix}"
    job_id = suffix

    publisher = StatusPublisher(
        redis_client,
        worker_id="worker-restart",
        config=StatusPublisherConfig(stream=stream),
    )

    first_consumer = StreamSubscriber(
        redis_client=redis_client,
        config=StreamSubscriberConfig(
            stream=stream,
            group=group,
            consumer_id=f"consumer-a-{suffix}",
            batch_size=10,
            poll_interval=0.01,
        ),
    )
    second_consumer = StreamSubscriber(
        redis_client=redis_client,
        config=StreamSubscriberConfig(
            stream=stream,
            group=group,
            consumer_id=f"consumer-b-{suffix}",
            batch_size=10,
            poll_interval=0.01,
        ),
    )
    assert await first_consumer._ensure_consumer_group() is True  # noqa: SLF001

    await publisher.record_job_started(
        job_id=job_id,
        function="task_key",
        function_name="task_name",
        attempt=1,
        max_retries=0,
        root_id=job_id,
    )
    assert await first_consumer._process_batch(drain=True) == 1  # noqa: SLF001

    await publisher.record_job_completed(
        job_id=job_id,
        function="task_key",
        function_name="task_name",
        root_id=job_id,
        attempt=1,
        result={"ok": True},
        duration_ms=12.0,
    )
    assert await second_consumer._process_batch(drain=True) == 1  # noqa: SLF001

    async with db.session() as session:
        row = await session.get(JobHistory, job_id)
        assert row is not None
        assert row.status == "complete"
