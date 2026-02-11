from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import server.services.api_tracking as api_tracking_module
import server.services.queue as queue_service_module
import server.services.workers as workers_service_module
from fakeredis.aioredis import FakeRedis
from shared.api import API_PREFIX
from shared.workers import (
    FUNCTION_KEY_PREFIX,
    WORKER_DEF_PREFIX,
    WORKER_INSTANCE_KEY_PREFIX,
)


@pytest.fixture
async def redis_text_client():
    client = FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_api_metrics_reader_aggregates_hourly_and_minute_buckets(
    redis_text_client,
) -> None:
    now = datetime.now(UTC)
    hour_key = now.strftime("%Y-%m-%dT%H")
    minute_key_1 = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
    minute_key_2 = (now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M")

    await redis_text_client.sadd(f"{API_PREFIX}:registry", "orders", "idle-api")
    await redis_text_client.sadd(
        f"{API_PREFIX}:orders:endpoints",
        "GET:/orders",
        "POST:/orders",
    )
    await redis_text_client.sadd(f"{API_PREFIX}:idle-api:endpoints", "GET:/idle")

    await redis_text_client.hset(
        f"{API_PREFIX}:orders:GET:/orders:h:{hour_key}",
        mapping={
            "requests": 10,
            "errors": 2,
            "total_latency_ms": 200,
            "status_2xx": 8,
            "status_4xx": 1,
            "status_5xx": 1,
        },
    )
    await redis_text_client.hset(
        f"{API_PREFIX}:orders:POST:/orders:h:{hour_key}",
        mapping={
            "requests": 5,
            "errors": 0,
            "total_latency_ms": 150,
            "status_2xx": 5,
            "status_4xx": 0,
            "status_5xx": 0,
        },
    )
    await redis_text_client.hset(
        f"{API_PREFIX}:orders:GET:/orders:m:{minute_key_1}",
        mapping={"requests": 6},
    )
    await redis_text_client.hset(
        f"{API_PREFIX}:orders:GET:/orders:m:{minute_key_2}",
        mapping={"requests": 4},
    )

    reader = api_tracking_module.ApiMetricsReader(redis_text_client)
    apis = await reader.get_apis()

    assert len(apis) == 1
    assert apis[0]["name"] == "orders"
    assert apis[0]["endpoint_count"] == 2
    assert apis[0]["requests_24h"] == 15
    assert apis[0]["avg_latency_ms"] == pytest.approx(23.33)
    assert apis[0]["error_rate"] == pytest.approx(13.3)
    assert apis[0]["requests_per_min"] == 5.0


@pytest.mark.asyncio
async def test_api_metrics_reader_endpoints_trends_summary_and_factory(
    redis_text_client, monkeypatch
) -> None:
    now = datetime.now(UTC)
    hour_key = now.strftime("%Y-%m-%dT%H")

    await redis_text_client.sadd(f"{API_PREFIX}:registry", "billing")
    await redis_text_client.sadd(
        f"{API_PREFIX}:billing:endpoints",
        "GET:/invoices",
        "BROKEN_ENDPOINT_KEY",
    )
    await redis_text_client.hset(
        f"{API_PREFIX}:billing:GET:/invoices:h:{hour_key}",
        mapping={
            "requests": 3,
            "errors": 1,
            "total_latency_ms": 90,
            "status_2xx": 2,
            "status_4xx": 1,
            "status_5xx": 0,
        },
    )

    reader = api_tracking_module.ApiMetricsReader(redis_text_client)

    filtered = await reader.get_endpoints(api_name="billing")
    assert len(filtered) == 1
    assert filtered[0]["api_name"] == "billing"
    assert filtered[0]["method"] == "GET"
    assert filtered[0]["path"] == "/invoices"

    all_endpoints = await reader.get_endpoints()
    assert len(all_endpoints) == 1

    trends = await reader.get_hourly_trends(hours=3)
    assert len(trends) == 3
    assert sum(item["success_2xx"] for item in trends) == 2
    assert sum(item["client_4xx"] for item in trends) == 1
    assert sum(item["server_5xx"] for item in trends) == 0

    summary = await reader.get_summary()
    assert summary["requests_24h"] == 3
    assert summary["avg_latency_ms"] == 30.0
    assert summary["error_rate"] == pytest.approx(33.3)

    async def fake_get_redis() -> FakeRedis:
        return redis_text_client

    monkeypatch.setattr(api_tracking_module, "get_redis", fake_get_redis)
    from_factory = await api_tracking_module.get_metrics_reader()
    assert isinstance(from_factory, api_tracking_module.ApiMetricsReader)


@pytest.mark.asyncio
async def test_workers_service_parses_and_lists_instances_and_definitions(
    redis_text_client, monkeypatch
) -> None:
    instance_payload = json.dumps(
        {
            "id": "worker-1",
            "worker_name": "alpha",
            "started_at": "2026-02-08T10:00:00Z",
            "last_heartbeat": "2026-02-08T10:00:05Z",
            "functions": ["fn.a"],
            "function_names": {"fn.a": "task-a"},
            "concurrency": 2,
            "active_jobs": 1,
            "jobs_processed": 9,
            "jobs_failed": 1,
            "hostname": "host-a",
        }
    )
    # Missing optional fields should use defaults.
    minimal_payload = json.dumps(
        {
            "id": "worker-2",
            "started_at": "2026-02-08T10:00:00Z",
            "last_heartbeat": "2026-02-08T10:00:05Z",
        }
    )

    await redis_text_client.set(
        f"{WORKER_INSTANCE_KEY_PREFIX}:worker-1", instance_payload
    )
    await redis_text_client.set(
        f"{WORKER_INSTANCE_KEY_PREFIX}:worker-2", minimal_payload
    )
    await redis_text_client.set(
        f"{WORKER_DEF_PREFIX}:alpha",
        json.dumps({"name": "alpha", "functions": ["fn.a"]}),
    )
    await redis_text_client.set(
        f"{FUNCTION_KEY_PREFIX}:fn.a",
        json.dumps({"key": "fn.a", "name": "task-a"}),
    )
    await redis_text_client.set(
        f"{FUNCTION_KEY_PREFIX}:legacy",
        json.dumps({"name": "fn.legacy"}),
    )
    await redis_text_client.set(
        f"{FUNCTION_KEY_PREFIX}:invalid",
        json.dumps({"timeout": 30}),
    )

    async def fake_get_redis() -> FakeRedis:
        return redis_text_client

    monkeypatch.setattr(workers_service_module, "get_redis", fake_get_redis)

    parsed = workers_service_module._parse_worker_instance(minimal_payload)  # noqa: SLF001
    assert parsed.worker_name == ""
    assert parsed.concurrency == 1
    assert parsed.active_jobs == 0

    worker = await workers_service_module.get_worker_instance("worker-1")
    assert worker is not None
    assert worker.worker_name == "alpha"

    missing = await workers_service_module.get_worker_instance("missing")
    assert missing is None

    listed = await workers_service_module.list_worker_instances()
    assert {w.id for w in listed} == {"worker-1", "worker-2"}

    defs = await workers_service_module.get_worker_definitions()
    assert defs["alpha"]["name"] == "alpha"

    stats = await workers_service_module.get_worker_stats()
    assert stats.total == 2

    functions = await workers_service_module.get_function_definitions()
    assert set(functions.keys()) == {"fn.a", "fn.legacy"}


@pytest.mark.asyncio
async def test_queue_service_reads_depth_from_stream_groups(
    redis_text_client, monkeypatch
) -> None:
    stream_a = "upnext:fn:fn.a:stream"
    stream_b = "upnext:fn:fn.b:stream"
    await redis_text_client.xgroup_create(stream_a, "workers", id="0", mkstream=True)
    await redis_text_client.xgroup_create(stream_b, "workers", id="0", mkstream=True)

    # stream_a => lag 2, pending 1
    for idx in range(3):
        await redis_text_client.xadd(stream_a, {"job_id": f"a-{idx}"})
    await redis_text_client.xreadgroup(
        groupname="workers",
        consumername="consumer-a",
        streams={stream_a: ">"},
        count=1,
    )

    # stream_b => lag 1, pending 2
    for idx in range(3):
        await redis_text_client.xadd(stream_b, {"job_id": f"b-{idx}"})
    await redis_text_client.xreadgroup(
        groupname="workers",
        consumername="consumer-b",
        streams={stream_b: ">"},
        count=2,
    )

    async def fake_get_redis() -> FakeRedis:
        return redis_text_client

    await redis_text_client.set(
        f"{WORKER_INSTANCE_KEY_PREFIX}:worker-1",
        json.dumps({"id": "w1", "active_jobs": 1, "concurrency": 2}),
    )
    await redis_text_client.set(
        f"{WORKER_INSTANCE_KEY_PREFIX}:worker-2",
        json.dumps({"id": "w2", "active_jobs": 2, "concurrency": 3}),
    )

    monkeypatch.setattr(queue_service_module, "get_redis", fake_get_redis)

    stats = await queue_service_module.get_queue_depth_stats()
    assert stats.waiting == 3
    assert stats.claimed == 3
    assert stats.running == 3
    assert stats.capacity == 5
    assert stats.total == 6


@pytest.mark.asyncio
async def test_queue_service_returns_zero_stats_when_redis_unavailable(
    monkeypatch,
) -> None:
    async def fake_get_redis() -> FakeRedis:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(queue_service_module, "get_redis", fake_get_redis)

    stats = await queue_service_module.get_queue_depth_stats()
    assert stats.waiting == 0
    assert stats.claimed == 0
    assert stats.running == 0
    assert stats.capacity == 0
    assert stats.total == 0
