from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from shared.domain.jobs import Job
from shared.contracts import MissedRunPolicy
from upnext.engine.queue.base import BaseQueue
from upnext.engine.registry import Registry
from upnext.sdk.worker import Worker


@dataclass
class _QueueRecorder:
    jobs: list[Job] = field(default_factory=list)
    fail_first: bool = False

    async def enqueue(self, job: Job, *, delay: float = 0.0) -> str:
        assert delay == 0.0
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("simulated enqueue failure")
        self.jobs.append(job)
        return job.id


def test_registry_validates_definitions_and_duplicate_names() -> None:
    registry = Registry()

    async def task() -> None:
        return None

    with pytest.raises(ValueError, match="retries must be >= 0"):
        registry.register_task("bad-retries", task, retries=-1)

    with pytest.raises(ValueError, match="retry_backoff must be >= 1"):
        registry.register_task("bad-backoff", task, retry_backoff=0.5)
    with pytest.raises(ValueError, match="rate_limit must be a non-empty string"):
        registry.register_task("bad-rate", task, rate_limit=" ")
    with pytest.raises(ValueError, match="rate_limit must match"):
        registry.register_task("bad-rate-format", task, rate_limit="10/x")
    with pytest.raises(ValueError, match="max_concurrency must be >= 1"):
        registry.register_task("bad-concurrency", task, max_concurrency=0)
    with pytest.raises(ValueError, match="routing_group must be a non-empty string"):
        registry.register_task("bad-group", task, routing_group="   ")
    with pytest.raises(ValueError, match="group_max_concurrency must be >= 1"):
        registry.register_task("bad-group-limit", task, group_max_concurrency=0)

    registry.register_task("ok-task", task)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_task("ok-task", task)


def test_registry_matches_event_patterns_and_clears_state() -> None:
    registry = Registry()

    async def on_user_event(**kwargs: Any) -> None:
        return None

    async def on_signup(**kwargs: Any) -> None:
        return None

    wildcard = registry.register_event(
        key="evt-user",
        display_name="user wildcard",
        func=on_user_event,
        event="user.*",
        retries=2,
    )
    exact = registry.register_event(
        key="evt-signup",
        display_name="signup exact",
        func=on_signup,
        event="user.signup",
    )

    matches = registry.get_events_for_event_name("user.signup")
    assert [event.key for event in matches] == [wildcard.key, exact.key]
    assert registry.get_task("evt-user") is not None
    assert registry.get_task_names() == ["evt-user", "evt-signup"]

    registry.clear()
    assert registry.tasks == {}
    assert registry.events == {}
    assert registry.crons == {}
    assert registry.apps == {}


def test_registry_cron_and_app_constraints() -> None:
    registry = Registry()

    def cron_job() -> None:
        return None

    registry.register_cron(
        key="cron-key",
        display_name="hourly",
        schedule="0 * * * *",
        func=cron_job,
        missed_run_policy=MissedRunPolicy.LATEST_ONLY,
        max_catch_up_seconds=300,
    )
    with pytest.raises(ValueError, match="already registered"):
        registry.register_cron(
            key="cron-key",
            display_name="hourly",
            schedule="0 * * * *",
            func=cron_job,
        )
    with pytest.raises(ValueError, match="max_catch_up_seconds must be > 0"):
        registry.register_cron(
            key="cron-bad-window",
            display_name="bad-window",
            schedule="0 * * * *",
            func=cron_job,
            max_catch_up_seconds=0,
        )

    with pytest.raises(ValueError, match="port must be 0-65535"):
        registry.register_app("bad-port", cron_job, port=70_000)

    with pytest.raises(ValueError, match="replicas must be >= 1"):
        registry.register_app("bad-replicas", cron_job, replicas=0)

    with pytest.raises(ValueError, match="cpu must be > 0"):
        registry.register_app("bad-cpu", cron_job, cpu=0)


@pytest.mark.asyncio
async def test_event_handle_enqueues_handlers_and_exposes_configs() -> None:
    worker = Worker(name="event-worker")
    order_created = worker.event("order.created")

    @order_created.on(
        name="notify",
        retries=2,
        retry_delay=3.0,
        timeout=12,
        rate_limit="10/s",
        max_concurrency=4,
        routing_group="orders",
        group_max_concurrency=6,
    )
    async def notify(order_id: str) -> None:
        return None

    @order_created.on
    async def audit(order_id: str) -> None:
        return None

    queue = _QueueRecorder()
    order_created._queue = cast(BaseQueue, queue)  # noqa: SLF001

    await order_created.send(order_id="ord-1")

    assert len(queue.jobs) == 2
    assert queue.jobs[0].function_name == "notify"
    assert queue.jobs[1].function_name == "audit"
    assert all(job.kwargs == {"order_id": "ord-1"} for job in queue.jobs)
    assert all(job.event_pattern == "order.created" for job in queue.jobs)
    assert queue.jobs[0].event_handler_name == "notify"
    assert queue.jobs[1].event_handler_name == "audit"

    assert order_created.handler_names == ["notify", "audit"]
    assert len(order_created.handler_keys) == 2
    configs = order_created.handler_configs()
    assert configs[0]["name"] == "notify"
    assert configs[0]["max_retries"] == 2
    assert configs[0]["retry_delay"] == 3.0
    assert configs[0]["timeout"] == 12
    assert configs[0]["rate_limit"] == "10/s"
    assert configs[0]["max_concurrency"] == 4
    assert configs[0]["routing_group"] == "orders"
    assert configs[0]["group_max_concurrency"] == 6

    assert worker._registry.get_task(order_created.handler_keys[0]) is not None  # noqa: SLF001
    assert "handlers=2" in repr(order_created)
    assert notify.__name__ == "notify"


def test_event_handle_rejects_duplicate_handler_names() -> None:
    worker = Worker(name="event-worker")
    order_created = worker.event("order.created")

    @order_created.on(name="notify")
    async def notify_first(order_id: str) -> None:
        return None

    with pytest.raises(ValueError, match="already registered"):

        @order_created.on(name="notify")
        async def notify_second(order_id: str) -> None:  # pragma: no cover
            return None

    assert notify_first.__name__ == "notify_first"


@pytest.mark.asyncio
async def test_event_handle_requires_queue_and_continues_after_enqueue_error() -> None:
    worker = Worker(name="event-worker")
    signup = worker.event("user.signup")

    @signup.on(name="fails-first")
    async def first(user_id: str) -> None:
        return None

    @signup.on(name="still-runs")
    async def second(user_id: str) -> None:
        return None

    with pytest.raises(RuntimeError, match="Worker not started"):
        await signup.send(user_id="u-1")

    queue = _QueueRecorder(fail_first=True)
    signup._queue = cast(BaseQueue, queue)  # noqa: SLF001
    await signup.send(user_id="u-1")

    assert len(queue.jobs) == 1
    assert queue.jobs[0].function_name == "still-runs"


@pytest.mark.asyncio
async def test_typed_event_send_maps_positional_args_to_kwargs() -> None:
    worker = Worker(name="typed-event-worker")
    user_changed = worker.event("user.changed")

    @user_changed.on
    async def handler(user_id: str, plan: str) -> None:
        return None

    queue = _QueueRecorder()
    user_changed._queue = cast(BaseQueue, queue)  # noqa: SLF001

    await handler.send("u-42", plan="pro")

    assert len(queue.jobs) == 1
    assert queue.jobs[0].kwargs == {"user_id": "u-42", "plan": "pro"}


@pytest.mark.asyncio
async def test_event_send_idempotent_applies_shared_key_to_handlers() -> None:
    worker = Worker(name="idempotent-event-worker")
    order_created = worker.event("order.created")

    @order_created.on
    async def notify(order_id: str) -> None:
        return None

    @order_created.on
    async def audit(order_id: str) -> None:
        return None

    queue = _QueueRecorder()
    order_created._queue = cast(BaseQueue, queue)  # noqa: SLF001

    await order_created.send_idempotent(" event:123 ", order_id="ord-1")

    assert len(queue.jobs) == 2
    assert all(job.key == "event:123" for job in queue.jobs)

    with pytest.raises(ValueError, match="idempotency_key must be a non-empty string"):
        await order_created.send_idempotent(" ", order_id="ord-1")
