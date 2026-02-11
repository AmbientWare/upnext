from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, cast

import pytest
import server.routes.events as events_route
import server.routes.events.events_stream as events_stream_route
from fastapi import HTTPException
from shared.events import EVENTS_PUBSUB_CHANNEL


@dataclass
class _PubSubStub:
    messages: list[dict[str, Any] | None]
    subscribed: list[str] = field(default_factory=list)
    unsubscribed: list[str] = field(default_factory=list)
    closed: bool = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

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
        self.unsubscribed.append(channel)

    async def close(self) -> None:
        self.closed = True


@dataclass
class _RedisStub:
    pubsub_instance: _PubSubStub

    def pubsub(self) -> _PubSubStub:
        return self.pubsub_instance


@pytest.mark.asyncio
async def test_stream_events_returns_503_when_redis_unavailable(monkeypatch) -> None:
    async def fail_get_redis():  # type: ignore[no-untyped-def]
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(events_stream_route, "get_redis", fail_get_redis)

    with pytest.raises(HTTPException, match="redis unavailable") as exc:
        await events_route.stream_events()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_stream_events_emits_frames_and_cleans_pubsub(monkeypatch) -> None:
    pubsub = _PubSubStub(
        messages=[
            {"type": "message", "data": b'{"job_id":"job-1"}'},
            None,
        ]
    )
    redis_stub = _RedisStub(pubsub_instance=pubsub)

    async def fake_get_redis() -> _RedisStub:
        return redis_stub

    monkeypatch.setattr(events_stream_route, "get_redis", fake_get_redis)

    response = await events_route.stream_events()
    assert response.media_type == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["Connection"] == "keep-alive"

    stream = cast(AsyncIterator[str], response.body_iterator.__aiter__())
    open_frame = await anext(stream)
    data_frame = await anext(stream)
    keep_alive = await anext(stream)

    closer = getattr(response.body_iterator, "aclose", None)
    if callable(closer):
        await cast(Callable[[], Awaitable[Any]], closer)()

    assert open_frame == "event: open\ndata: connected\n\n"
    assert data_frame == 'data: {"job_id":"job-1"}\n\n'
    assert keep_alive == ": keep-alive\n\n"
    assert pubsub.subscribed == [EVENTS_PUBSUB_CHANNEL]
    assert pubsub.unsubscribed == [EVENTS_PUBSUB_CHANNEL]
    assert pubsub.closed is True
