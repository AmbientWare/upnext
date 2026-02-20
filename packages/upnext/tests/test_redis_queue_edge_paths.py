from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
import redis.asyncio as redis
from shared.domain.jobs import Job, JobStatus
from upnext.engine.queue.redis.queue import RedisQueue


@pytest.mark.asyncio
async def test_enqueue_fails_fast_when_script_loading_fails(
    fake_redis, monkeypatch
) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-script-required")

    async def fail_script_load(script: str) -> str:  # noqa: ARG001
        raise RuntimeError("script load failed")

    monkeypatch.setattr(fake_redis, "script_load", fail_script_load)

    job = Job(function="task_fn", function_name="task", key="script-required-key")
    with pytest.raises(RuntimeError, match="Failed to load required Redis Lua scripts"):
        await queue.enqueue(job)


@pytest.mark.asyncio
async def test_enqueue_recovers_from_noscript_by_reloading_scripts(
    fake_redis, monkeypatch
) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-noscript-reload")

    original_evalsha = fake_redis.evalsha
    original_script_load = fake_redis.script_load
    state = {"raised": False}
    loads = {"count": 0}

    async def flaky_evalsha(*args, **kwargs):  # noqa: ANN002, ANN003
        if not state["raised"]:
            state["raised"] = True
            raise redis.ResponseError("NOSCRIPT No matching script. Please use EVAL.")
        return await original_evalsha(*args, **kwargs)

    async def tracked_script_load(script: str) -> str:
        loads["count"] += 1
        return await original_script_load(script)

    monkeypatch.setattr(fake_redis, "evalsha", flaky_evalsha)
    monkeypatch.setattr(fake_redis, "script_load", tracked_script_load)

    job = Job(function="task_fn", function_name="task", key="noscript-reload-key")
    await queue.enqueue(job)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    assert active.id == job.id
    assert state["raised"] is True
    # 8 scripts loaded initially + 8 reloaded after NOSCRIPT.
    assert loads["count"] >= 16


@pytest.mark.asyncio
async def test_dequeue_direct_recovers_after_nogroup_error(
    fake_redis, monkeypatch
) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-nogroup-direct")
    job = Job(function="task_fn", function_name="task", key="nogroup-direct-key")
    await queue.enqueue(job)

    original_xreadgroup = fake_redis.xreadgroup
    state = {"raised": False}

    async def flaky_xreadgroup(*args, **kwargs):  # noqa: ANN002, ANN003
        if not state["raised"]:
            state["raised"] = True
            raise redis.ResponseError("NOGROUP consumer group does not exist")
        return await original_xreadgroup(*args, **kwargs)

    monkeypatch.setattr(fake_redis, "xreadgroup", flaky_xreadgroup)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    assert active.id == job.id
    assert state["raised"] is True


@pytest.mark.asyncio
async def test_dequeue_batch_recovers_after_nogroup_error(
    fake_redis, monkeypatch
) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-nogroup-batch")
    job = Job(function="task_fn", function_name="task", key="nogroup-batch-key")
    await queue.enqueue(job)

    original_xreadgroup = fake_redis.xreadgroup
    state = {"raised": False}

    async def flaky_xreadgroup(*args, **kwargs):  # noqa: ANN002, ANN003
        if not state["raised"]:
            state["raised"] = True
            raise redis.ResponseError("NOGROUP missing")
        return await original_xreadgroup(*args, **kwargs)

    monkeypatch.setattr(fake_redis, "xreadgroup", flaky_xreadgroup)

    jobs = await queue._dequeue_batch(["task_fn"], count=1, timeout=0.2)  # noqa: SLF001
    assert len(jobs) == 1
    assert jobs[0].id == job.id
    assert state["raised"] is True


@pytest.mark.asyncio
async def test_missing_payload_without_result_is_acked(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-missing-payload-pending")
    job = Job(function="task_fn", function_name="task", key="missing-payload-pending")
    await queue.enqueue(job)

    client = await queue._ensure_connected()  # noqa: SLF001
    await client.delete(queue._job_key(job))  # noqa: SLF001

    active = await queue.dequeue(["task_fn"], timeout=0.1)
    assert active is None

    pending = await client.xpending(queue._stream_key("task_fn"), queue._consumer_group)  # noqa: SLF001
    assert pending["pending"] == 0


@pytest.mark.asyncio
async def test_malformed_stream_payload_missing_identifiers_is_acked(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-malformed-payload")
    client = await queue._ensure_connected()  # noqa: SLF001
    stream_key = queue._stream_key("task_fn")  # noqa: SLF001
    await queue._ensure_consumer_group(stream_key)  # noqa: SLF001

    malformed = Job(function="task_fn", function_name="task", key="malformed-payload")
    await client.xadd(stream_key, {"data": malformed.to_json()})

    active = await queue.dequeue(["task_fn"], timeout=0.1)
    assert active is None

    pending = await client.xpending(stream_key, queue._consumer_group)  # noqa: SLF001
    assert pending["pending"] == 0


@pytest.mark.asyncio
async def test_missing_payload_is_acked_as_stale_stream_entry(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-missing-payload-acked")
    job = Job(function="task_fn", function_name="task", key="missing-payload-acked")
    await queue.enqueue(job)

    client = await queue._ensure_connected()  # noqa: SLF001
    await client.delete(queue._job_key(job))  # noqa: SLF001

    active = await queue.dequeue(["task_fn"], timeout=0.1)
    assert active is None

    pending = await client.xpending(queue._stream_key("task_fn"), queue._consumer_group)  # noqa: SLF001
    assert pending["pending"] == 0


@pytest.mark.asyncio
async def test_heartbeat_restores_job_ttls_when_missing(fake_redis) -> None:
    queue = RedisQueue(
        client=fake_redis,
        key_prefix="upnext-heartbeat-refresh",
        job_ttl_seconds=5,
    )
    job = Job(function="task_fn", function_name="task", key="heartbeat-refresh")
    await queue.enqueue(job)

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None

    client = await queue._ensure_connected()  # noqa: SLF001
    job_key = queue._job_key(active)  # noqa: SLF001
    job_index_key = queue._job_index_key(active.id)  # noqa: SLF001

    await client.persist(job_key)
    await client.persist(job_index_key)
    assert await client.ttl(job_key) == -1
    assert await client.ttl(job_index_key) == -1

    await queue.heartbeat_active_jobs([active])

    assert await client.ttl(job_key) > 0
    assert await client.ttl(job_index_key) > 0


@pytest.mark.asyncio
async def test_find_job_key_by_id_rebuilds_stale_index(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-index-rebuild")
    job = Job(function="task_fn", function_name="task", key="stale-index-key")
    await queue.enqueue(job)

    client = await queue._ensure_connected()  # noqa: SLF001
    stale_key = "upnext-index-rebuild:job:task_fn:missing"
    await client.set(queue._job_index_key(job.id), stale_key)  # noqa: SLF001

    resolved = await queue._find_job_key_by_id(job.id)  # noqa: SLF001
    assert resolved == queue._job_key(job)  # noqa: SLF001

    rebuilt = await client.get(queue._job_index_key(job.id))  # noqa: SLF001
    rebuilt_str = rebuilt.decode() if isinstance(rebuilt, bytes) else rebuilt
    assert rebuilt_str == queue._job_key(job)  # noqa: SLF001


@dataclass
class _PubSubStub:
    messages: list[dict[str, Any] | None]
    subscribed_to: list[str]
    unsubscribed_to: list[str]
    closed: bool = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed_to.append(channel)

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,  # noqa: ARG002
        timeout: float,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        if self.messages:
            return self.messages.pop(0)
        return None

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed_to.append(channel)

    async def close(self) -> None:
        self.closed = True


@dataclass
class _RedisWithPubSubStub:
    pubsub_instance: _PubSubStub

    def pubsub(self) -> _PubSubStub:
        return self.pubsub_instance


@pytest.mark.asyncio
async def test_subscribe_job_returns_terminal_status_without_pubsub(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="upnext-subscribe-terminal")

    job = Job(function="task_fn", function_name="task", key="terminal-subscribe-key")
    await queue.enqueue(job)
    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    await queue.finish(active, JobStatus.COMPLETE)

    status = await queue.subscribe_job(job.id, timeout=0.05)
    assert status == JobStatus.COMPLETE.value


@pytest.mark.asyncio
async def test_subscribe_job_decodes_message_and_cleans_up() -> None:
    pubsub = _PubSubStub(
        messages=[{"type": "message", "data": b"failed"}],
        subscribed_to=[],
        unsubscribed_to=[],
    )
    redis_stub = _RedisWithPubSubStub(pubsub_instance=pubsub)

    queue = RedisQueue(client=redis_stub, key_prefix="upnext-subscribe-message")
    queue._scripts_loaded = True  # noqa: SLF001

    async def no_job(_job_id: str):  # type: ignore[no-untyped-def]
        return None

    queue.get_job = no_job  # type: ignore[method-assign]

    status = await queue.subscribe_job("job-subscribe-1", timeout=0.1)
    assert status == "failed"
    assert pubsub.subscribed_to == ["upnext:job:job-subscribe-1"]
    assert pubsub.unsubscribed_to == ["upnext:job:job-subscribe-1"]
    assert pubsub.closed is True


@pytest.mark.asyncio
async def test_subscribe_job_timeout_cleans_up_pubsub() -> None:
    pubsub = _PubSubStub(messages=[None, None], subscribed_to=[], unsubscribed_to=[])
    redis_stub = _RedisWithPubSubStub(pubsub_instance=pubsub)

    queue = RedisQueue(client=redis_stub, key_prefix="upnext-subscribe-timeout")
    queue._scripts_loaded = True  # noqa: SLF001

    async def no_job(_job_id: str):  # type: ignore[no-untyped-def]
        return None

    queue.get_job = no_job  # type: ignore[method-assign]

    with pytest.raises(TimeoutError) as timeout_exc:
        await queue.subscribe_job("job-timeout-1", timeout=0.01)
    if timeout_exc.value.args:
        assert "job-timeout-1" in str(timeout_exc.value)

    assert pubsub.unsubscribed_to == ["upnext:job:job-timeout-1"]
    assert pubsub.closed is True


@pytest.mark.asyncio
async def test_subscribe_job_returns_terminal_status_without_pubsub_message() -> None:
    pubsub = _PubSubStub(messages=[None, None], subscribed_to=[], unsubscribed_to=[])
    redis_stub = _RedisWithPubSubStub(pubsub_instance=pubsub)

    queue = RedisQueue(client=redis_stub, key_prefix="upnext-subscribe-race")
    queue._scripts_loaded = True  # noqa: SLF001

    calls = {"count": 0}

    async def eventually_terminal(job_id: str) -> Job | None:
        calls["count"] += 1
        if calls["count"] < 2:
            return None
        return Job(
            id=job_id,
            function="task_fn",
            function_name="task",
            status=JobStatus.COMPLETE,
            root_id=job_id,
        )

    queue.get_job = eventually_terminal  # type: ignore[method-assign]

    status = await queue.subscribe_job("job-race-1", timeout=0.1)
    assert status == JobStatus.COMPLETE.value
    assert pubsub.subscribed_to == ["upnext:job:job-race-1"]
    assert pubsub.unsubscribed_to == ["upnext:job:job-race-1"]
    assert pubsub.closed is True
