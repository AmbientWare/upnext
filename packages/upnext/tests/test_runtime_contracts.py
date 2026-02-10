from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import upnext
from fastapi import APIRouter
from shared.api import API_INSTANCE_PREFIX
from shared.models import Job, JobStatus
from upnext.config import get_settings
from upnext.engine import cron as cron_module
from upnext.engine.cron import calculate_next_cron_run, calculate_next_cron_timestamp
from upnext.engine.event_router import Event, get_event_router
from upnext.engine.queue.base import BaseQueue
from upnext.sdk.api import Api
from upnext.sdk.task import Future
from upnext.sdk.worker import Worker


@dataclass
class _FutureQueue:
    job: Job | None = None
    timeout_calls: list[float | None] = field(default_factory=list)
    cancelled_job_id: str | None = None

    async def subscribe_job(self, job_id: str, timeout: float | None = None) -> str:
        self.timeout_calls.append(timeout)
        return JobStatus.COMPLETE.value

    async def get_job(self, job_id: str) -> Job | None:
        return self.job

    async def cancel(self, job_id: str) -> bool:
        self.cancelled_job_id = job_id
        return True


class _TrackingRedis:
    def __init__(self) -> None:
        self.setex_calls: list[tuple[str, int, str]] = []
        self.deleted: list[str] = []
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        return 1

    async def aclose(self) -> None:
        self.closed = True


class _BrokenRedis:
    async def ping(self) -> None:
        raise ConnectionError("redis unavailable")


@pytest.mark.asyncio
async def test_future_result_and_cancel_contracts() -> None:
    queue = _FutureQueue(
        job=Job(
            id="job-1",
            function="task-key",
            function_name="task-name",
            status=JobStatus.COMPLETE,
            result=42,
            attempts=2,
            root_id="job-1",
        )
    )
    future = Future[int]("job-1", queue=cast(BaseQueue, queue))

    result = await future.result(timeout=3.5)
    assert result.ok is True
    assert result.value == 42
    assert result.attempts == 2
    assert queue.timeout_calls == [3.5]

    assert await future.cancel() is True
    assert queue.cancelled_job_id == "job-1"


@pytest.mark.asyncio
async def test_future_result_raises_when_completed_job_is_missing() -> None:
    future = Future[int]("missing", queue=cast(BaseQueue, _FutureQueue(job=None)))

    with pytest.raises(RuntimeError, match="not found after completion"):
        await future.result(timeout=1)


def test_settings_environment_flags_and_cache(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("UPNEXT_ENV", "production")

    production = get_settings()
    assert production.is_production is True
    assert production.is_development is False
    assert get_settings() is production

    get_settings.cache_clear()
    monkeypatch.setenv("UPNEXT_ENV", "development")
    development = get_settings()
    assert development.is_production is False
    assert development.is_development is True
    get_settings.cache_clear()


def test_upnext_run_passes_components_and_timeouts(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_services(
        apis: list[Api],
        workers: list[Worker],
        *,
        worker_timeout: float,
        api_timeout: float,
    ) -> None:
        captured["apis"] = apis
        captured["workers"] = workers
        captured["worker_timeout"] = worker_timeout
        captured["api_timeout"] = api_timeout

    def run_coro(coro: Any) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr(upnext, "run_services", fake_run_services)
    monkeypatch.setattr(upnext.asyncio, "run", run_coro)

    api = upnext.Api("api-test", redis_url=None)
    worker = upnext.Worker("worker-test", redis_url="redis://ignored")
    upnext.run(api, worker, worker_timeout=7.5, api_timeout=2.25)

    assert captured["apis"] == [api]
    assert captured["workers"] == [worker]
    assert captured["worker_timeout"] == 7.5
    assert captured["api_timeout"] == 2.25


def test_upnext_run_ignores_keyboard_interrupt(monkeypatch) -> None:
    async def fake_run_services(*args: Any, **kwargs: Any) -> None:
        return None

    called = {"asyncio_run": False}

    def raise_keyboard_interrupt(coro: Any) -> None:
        called["asyncio_run"] = True
        assert asyncio.iscoroutine(coro)
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(upnext, "run_services", fake_run_services)
    monkeypatch.setattr(upnext.asyncio, "run", raise_keyboard_interrupt)

    assert upnext.run() is None
    assert called["asyncio_run"] is True


def test_event_router_event_round_trip_and_singleton(monkeypatch) -> None:
    event = Event(name="user.signup", data={"user_id": "u-1"}, source="tests")
    restored = Event.from_dict(event.to_dict())

    assert restored.name == "user.signup"
    assert restored.data == {"user_id": "u-1"}
    assert restored.source == "tests"

    monkeypatch.setattr("upnext.engine.event_router._router", None)
    first = get_event_router()
    second = get_event_router()
    assert first is second


def test_cron_helpers_handle_naive_time_six_field_and_float_results(
    monkeypatch,
) -> None:
    base = datetime(2026, 2, 8, 12, 0, 0)  # naive
    next_minute = calculate_next_cron_run("* * * * *", base)
    assert next_minute.tzinfo == UTC
    assert next_minute > base.replace(tzinfo=UTC)

    next_second = calculate_next_cron_run(
        "* * * * * *",
        datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )
    assert next_second.tzinfo == UTC
    assert next_second > datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC)

    class _FloatCroniter:
        def get_next(self, _kind: Any) -> float:
            return 1_762_629_120.0

    monkeypatch.setattr(
        cron_module, "croniter", lambda *_args, **_kwargs: _FloatCroniter()
    )
    from_float = calculate_next_cron_run(
        "* * * * *",
        datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
    )
    assert from_float == datetime.fromtimestamp(1_762_629_120.0, UTC)
    assert (
        calculate_next_cron_timestamp(
            "* * * * *",
            datetime(2026, 2, 8, 12, 0, 0, tzinfo=UTC),
        )
        == 1_762_629_120.0
    )


def test_api_route_helpers_and_repr() -> None:
    api = Api(name="contract-api", redis_url=None)

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/orders")
    async def create_order() -> dict[str, str]:
        return {"id": "1"}

    @api.put("/orders/{order_id}")
    async def update_order(order_id: str) -> dict[str, str]:
        return {"id": order_id}

    @api.patch("/orders/{order_id}")
    async def patch_order(order_id: str) -> dict[str, str]:
        return {"id": order_id}

    @api.delete("/orders/{order_id}")
    async def delete_order(order_id: str) -> dict[str, str]:
        return {"id": order_id}

    @api.route("/custom", methods=["OPTIONS"])
    async def custom() -> dict[str, str]:
        return {"ok": "true"}

    grouped = api.group("/v1")

    @grouped.get("/users")
    async def users() -> list[str]:
        return []

    extra = APIRouter(prefix="/extra")

    @extra.get("/status")
    async def extra_status() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(extra)

    endpoint_list = api._get_endpoint_list()  # noqa: SLF001
    assert "GET:/health" in endpoint_list
    assert "POST:/orders" in endpoint_list
    assert "GET:/extra/status" in endpoint_list

    routes = api.routes
    assert any(route["path"] == "/v1/users" for route in routes)
    assert any(route["path"] == "/orders/{order_id}" for route in routes)
    assert "routes=" in repr(api)


@pytest.mark.asyncio
async def test_api_tracking_setup_and_cleanup(monkeypatch) -> None:
    fake_redis = _TrackingRedis()
    monkeypatch.setattr(
        "upnext.sdk.api.aioredis.from_url", lambda *_args, **_kwargs: fake_redis
    )

    api = Api(name="tracked-api", redis_url="redis://fake")
    await api._setup_tracking()  # noqa: SLF001

    assert api.api_id is not None
    assert api.api_id.startswith("api_")
    assert len(fake_redis.setex_calls) == 1

    key, _ttl, payload = fake_redis.setex_calls[0]
    assert key.startswith(f"{API_INSTANCE_PREFIX}:api_")
    decoded = json.loads(payload)
    assert decoded["api_name"] == "tracked-api"
    assert decoded["port"] == 8000

    await api._cleanup_tracking()  # noqa: SLF001
    assert fake_redis.closed is True
    assert fake_redis.deleted == [f"{API_INSTANCE_PREFIX}:{api.api_id}"]
    assert api._heartbeat_task is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_api_tracking_setup_handles_redis_connection_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "upnext.sdk.api.aioredis.from_url", lambda *_args, **_kwargs: _BrokenRedis()
    )

    api = Api(name="no-redis-api", redis_url="redis://missing")
    await api._setup_tracking()  # noqa: SLF001

    assert api.api_id is None
    assert api._redis is None  # noqa: SLF001
    assert api._heartbeat_task is None  # noqa: SLF001


def test_api_stop_sets_server_exit_flag() -> None:
    class _Server:
        should_exit = False

    api = Api(name="stop-api", redis_url=None)
    api._server = _Server()  # noqa: SLF001
    api.stop()
    assert api._server.should_exit is True  # noqa: SLF001
