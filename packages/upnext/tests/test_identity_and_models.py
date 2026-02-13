from __future__ import annotations

from datetime import UTC, datetime

from shared.domain.jobs import Job
from upnext.engine.event_router import EventRouter
from upnext.engine.function_identity import build_function_key


def test_function_key_is_stable_for_same_input() -> None:
    first = build_function_key(
        "task",
        module="svc.jobs",
        qualname="ProcessOrder.run",
        name="Process Order",
    )
    second = build_function_key(
        "task",
        module="svc.jobs",
        qualname="ProcessOrder.run",
        name="Process Order",
    )
    assert first == second


def test_function_key_changes_with_discriminators() -> None:
    base = build_function_key(
        "task",
        module="svc.jobs",
        qualname="ProcessOrder.run",
        name="Process Order",
    )
    kind_change = build_function_key(
        "cron",
        module="svc.jobs",
        qualname="ProcessOrder.run",
        name="Process Order",
        schedule="* * * * *",
    )
    name_change = build_function_key(
        "task",
        module="svc.jobs",
        qualname="ProcessOrder.run",
        name="Process Payment",
    )
    pattern_change = build_function_key(
        "event",
        module="svc.jobs",
        qualname="ProcessOrder.run",
        name="Process Order",
        pattern="order.*",
    )

    assert base != kind_change
    assert base != name_change
    assert base != pattern_change


def test_job_state_history_and_duration_are_consistent() -> None:
    job = Job(function="task_key", function_name="task_name")
    job.mark_queued()
    job.mark_started("worker_a")

    job.started_at = datetime(2026, 2, 8, 10, 0, 0, tzinfo=UTC)
    job.completed_at = datetime(2026, 2, 8, 10, 0, 2, tzinfo=UTC)
    job.mark_complete(result={"ok": True})
    job.completed_at = datetime(2026, 2, 8, 10, 0, 2, tzinfo=UTC)

    assert [t.state for t in job.state_history] == ["queued", "active", "complete"]
    assert job.duration_ms == 2000


def test_event_router_matches_patterns_and_unregisters_named_handler() -> None:
    router = EventRouter()

    async def on_user(event: object) -> None:  # pragma: no cover - signature only
        return None

    async def on_signup(event: object) -> None:  # pragma: no cover - signature only
        return None

    router.register("user.*", on_user, name="user_wildcard")
    router.register("user.signup", on_signup, name="signup_exact")

    matched_names = [event.name for event in router.match("user.signup")]
    assert matched_names == ["user_wildcard", "signup_exact"]

    assert router.unregister("user_wildcard") is True
    assert [event.name for event in router.match("user.signup")] == ["signup_exact"]
    assert router.unregister("missing") is False
