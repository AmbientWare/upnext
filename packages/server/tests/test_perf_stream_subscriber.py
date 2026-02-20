from __future__ import annotations

from time import perf_counter
import statistics

import pytest

import server.services.events.subscriber as subscriber_module
from server.services.events import StreamSubscriber, StreamSubscriberConfig
from upnext.engine.status import StatusPublisher, StatusPublisherConfig


@pytest.mark.performance
@pytest.mark.asyncio
async def test_perf_stream_subscriber_ingestion_throughput(
    sqlite_db,  # noqa: ARG001 - initializes global DB used by subscriber
    fake_redis,
    monkeypatch,
) -> None:
    stream = "upnext:status:events:perf"
    config = StreamSubscriberConfig(
        stream=stream,
        group="server-subscribers-perf",
        consumer_id="subscriber-perf",
        batch_size=500,
        poll_interval=0.01,
        stale_claim_ms=1_000,
    )
    subscriber = StreamSubscriber(redis_client=fake_redis, config=config)
    assert await subscriber._ensure_consumer_group() is True  # noqa: SLF001

    publish_started: dict[str, float] = {}
    latencies_ms: list[float] = []

    async def fake_process_event(event: object, session=None) -> bool:  # noqa: ANN001
        _ = session
        job_id = getattr(event, "job_id", "")
        started = publish_started.pop(str(job_id), None)
        if started is not None:
            latencies_ms.append((perf_counter() - started) * 1000)
        return True

    monkeypatch.setattr(subscriber_module, "process_event", fake_process_event)

    publisher = StatusPublisher(
        fake_redis,
        worker_id="worker-perf",
        config=StatusPublisherConfig(stream=stream, max_stream_len=200_000),
    )

    total_events = 2_000
    for idx in range(total_events):
        job_id = f"perf-job-{idx}"
        publish_started[job_id] = perf_counter()
        await publisher.record_job_started(
            job_id=job_id,
            job_key=job_id,
            function="fn.perf",
            function_name="perf",
            attempt=1,
            max_retries=0,
            root_id=job_id,
        )

    processed_total = 0
    consume_start = perf_counter()
    while processed_total < total_events:
        processed = await subscriber._process_batch(drain=True)  # noqa: SLF001
        if processed == 0:
            break
        processed_total += processed
    consume_elapsed = max(perf_counter() - consume_start, 1e-9)

    events_per_second = processed_total / consume_elapsed
    p95_latency_ms = (
        statistics.quantiles(latencies_ms, n=20)[18]
        if len(latencies_ms) >= 20
        else (max(latencies_ms) if latencies_ms else 0.0)
    )
    print(
        "stream_subscriber_perf "
        f"processed={processed_total} "
        f"eps={events_per_second:.1f} "
        f"p95_ms={p95_latency_ms:.2f}"
    )

    assert processed_total == total_events
    assert events_per_second > 0
