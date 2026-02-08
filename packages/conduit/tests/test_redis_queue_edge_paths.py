from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
import redis.asyncio as redis

from conduit.engine.queue.redis.queue import RedisQueue
from shared.models import Job, JobStatus


@pytest.mark.asyncio
async def test_enqueue_falls_back_when_script_loading_fails(fake_redis, monkeypatch) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="conduit-script-fallback")

    async def fail_script_load(script: str) -> str:  # noqa: ARG001
        raise RuntimeError("script load failed")

    monkeypatch.setattr(fake_redis, "script_load", fail_script_load)

    job = Job(function="task_fn", function_name="task", key="script-fallback-key")
    await queue.enqueue(job)

    # Script loading failed, so enqueue should have used the non-Lua fallback path.
    assert queue._scripts_loaded is False  # noqa: SLF001

    active = await queue.dequeue(["task_fn"], timeout=0.2)
    assert active is not None
    assert active.id == job.id


@pytest.mark.asyncio
async def test_dequeue_direct_recovers_after_nogroup_error(fake_redis, monkeypatch) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="conduit-nogroup-direct")
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
async def test_dequeue_batch_recovers_after_nogroup_error(fake_redis, monkeypatch) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="conduit-nogroup-batch")
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
async def test_find_job_key_by_id_rebuilds_stale_index(fake_redis) -> None:
    queue = RedisQueue(client=fake_redis, key_prefix="conduit-index-rebuild")
    job = Job(function="task_fn", function_name="task", key="stale-index-key")
    await queue.enqueue(job)

    client = await queue._ensure_connected()  # noqa: SLF001
    stale_key = "conduit-index-rebuild:job:task_fn:missing"
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
    queue = RedisQueue(client=fake_redis, key_prefix="conduit-subscribe-terminal")

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

    queue = RedisQueue(client=redis_stub, key_prefix="conduit-subscribe-message")
    queue._scripts_loaded = True  # noqa: SLF001

    async def no_job(_job_id: str):  # type: ignore[no-untyped-def]
        return None

    queue.get_job = no_job  # type: ignore[method-assign]

    status = await queue.subscribe_job("job-subscribe-1", timeout=0.1)
    assert status == "failed"
    assert pubsub.subscribed_to == ["conduit:job:job-subscribe-1"]
    assert pubsub.unsubscribed_to == ["conduit:job:job-subscribe-1"]
    assert pubsub.closed is True


@pytest.mark.asyncio
async def test_subscribe_job_timeout_cleans_up_pubsub() -> None:
    pubsub = _PubSubStub(messages=[None, None], subscribed_to=[], unsubscribed_to=[])
    redis_stub = _RedisWithPubSubStub(pubsub_instance=pubsub)

    queue = RedisQueue(client=redis_stub, key_prefix="conduit-subscribe-timeout")
    queue._scripts_loaded = True  # noqa: SLF001

    async def no_job(_job_id: str):  # type: ignore[no-untyped-def]
        return None

    queue.get_job = no_job  # type: ignore[method-assign]

    with pytest.raises(TimeoutError) as timeout_exc:
        await queue.subscribe_job("job-timeout-1", timeout=0.01)
    if timeout_exc.value.args:
        assert "job-timeout-1" in str(timeout_exc.value)

    assert pubsub.unsubscribed_to == ["conduit:job:job-timeout-1"]
    assert pubsub.closed is True
