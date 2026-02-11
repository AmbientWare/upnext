from __future__ import annotations

import json

import pytest
from shared.workers import FUNCTION_KEY_PREFIX, WORKER_DEF_PREFIX
from shared.schemas import MissedRunPolicy
from upnext.sdk.worker import Worker


class _NoopJobProcessor:
    def __init__(self, *args, **kwargs) -> None:
        self.active_job_count = 0
        self.jobs_processed = 0
        self.jobs_failed = 0

    async def start(self) -> None:
        return None

    async def stop(self, timeout: float = 30.0) -> None:
        return None


@pytest.mark.asyncio
async def test_worker_writes_worker_and_function_definitions(
    fake_redis, monkeypatch
) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )
    monkeypatch.setattr("upnext.sdk.worker.JobProcessor", _NoopJobProcessor)

    worker = Worker(name="writer-worker")

    @worker.task(
        name="health_check",
        retries=2,
        retry_delay=3,
        timeout=45,
        rate_limit="25/m",
        max_concurrency=3,
        routing_group="ops",
        group_max_concurrency=5,
    )
    async def health_check() -> str:
        return "ok"

    handle = worker.tasks["health_check"]

    worker.initialize(redis_url="redis://ignored")
    await worker.start()
    try:
        worker_def_raw = await fake_redis.get(f"{WORKER_DEF_PREFIX}:writer-worker")
        assert worker_def_raw is not None
        worker_def = json.loads(worker_def_raw)
        assert worker_def["name"] == "writer-worker"
        assert worker_def["functions"] == [handle.function_key]

        function_def_raw = await fake_redis.get(
            f"{FUNCTION_KEY_PREFIX}:{handle.function_key}"
        )
        assert function_def_raw is not None
        function_def = json.loads(function_def_raw)
        assert function_def["key"] == handle.function_key
        assert function_def["name"] == "health_check"
        assert function_def["timeout"] == 45
        assert function_def["rate_limit"] == "25/m"
        assert function_def["max_concurrency"] == 3
        assert function_def["routing_group"] == "ops"
        assert function_def["group_max_concurrency"] == 5
    finally:
        await worker.stop(timeout=0.1)


@pytest.mark.asyncio
async def test_execute_helper_accepts_display_name_and_function_key(
    fake_redis, monkeypatch
) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )

    worker = Worker(name="execute-worker", redis_url="redis://ignored")

    @worker.task(name="add")
    async def add(x: int, y: int) -> int:
        return x + y

    result_by_name = await worker.execute("add", {"x": 1, "y": 2})
    result_by_key = await worker.execute(add.function_key, {"x": 4, "y": 5})

    assert result_by_name == 3
    assert result_by_key == 9

    events = await fake_redis.xrange("upnext:status:events", count=20)
    event_types = [row[1][b"type"].decode() for row in events]
    assert event_types.count("job.started") == 2
    assert event_types.count("job.completed") == 2


@pytest.mark.asyncio
async def test_worker_writes_cron_policy_fields(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )
    monkeypatch.setattr("upnext.sdk.worker.JobProcessor", _NoopJobProcessor)

    worker = Worker(name="cron-policy-worker")

    @worker.cron(
        "* * * * *",
        name="tick",
        missed_run_policy=MissedRunPolicy.SKIP,
        max_catch_up_seconds=120,
    )
    async def tick() -> None:
        return None

    worker.initialize(redis_url="redis://ignored")
    await worker.start()
    try:
        cron_key = worker.crons[0].key
        function_def_raw = await fake_redis.get(f"{FUNCTION_KEY_PREFIX}:{cron_key}")
        assert function_def_raw is not None
        cron_def = json.loads(function_def_raw)

        assert cron_def["type"] == "cron"
        assert cron_def["missed_run_policy"] == "skip"
        assert cron_def["max_catch_up_seconds"] == 120
    finally:
        await worker.stop(timeout=0.1)
