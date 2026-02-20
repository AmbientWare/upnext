from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import server.services.events.processing as event_processing_module
from server.db.repositories import ArtifactRepository
from server.db.tables import Artifact, JobHistory, PendingArtifact
from server.services.events import process_event
from server.shared_utils import as_utc_aware
from shared.contracts import (
    JobCancelledEvent,
    JobCheckpointEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobRetryingEvent,
    JobStartedEvent,
)


def _started(payload: dict[str, object]) -> JobStartedEvent:
    if "job_key" not in payload:
        payload = {**payload, "job_key": str(payload["job_id"])}
    return JobStartedEvent.model_validate(payload)


@pytest.mark.asyncio
async def test_job_started_duplicate_is_ignored(sqlite_db) -> None:
    started_at = datetime.now(UTC)
    payload = {
        "job_id": "job-start-1",
        "function": "task_key",
        "function_name": "task_name",
        "root_id": "job-start-1",
        "attempt": 1,
        "max_retries": 2,
        "started_at": started_at,
        "scheduled_at": started_at - timedelta(seconds=2),
        "queue_wait_ms": 250.5,
        "kwargs": {"x": 1},
    }

    first = await process_event(
        _started({**payload, "worker_id": "worker-a"})
    )
    assert first is True

    stale = dict(payload)
    stale["started_at"] = started_at - timedelta(seconds=1)
    second = await process_event(
        _started({**stale, "worker_id": "worker-a"})
    )
    assert second is False

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-start-1")
        assert row is not None
        assert row.status == "active"
        assert row.attempts == 1
        assert as_utc_aware(row.started_at) == started_at
        assert row.queue_wait_ms == pytest.approx(250.5)
        assert row.cron_window_at is None
        assert row.event_pattern is None


@pytest.mark.asyncio
async def test_job_failed_stale_event_does_not_override_terminal_state(
    sqlite_db,
) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        _started(
            {
                "job_id": "job-fail-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-fail-1",
                "attempt": 2,
                "max_retries": 2,
                "started_at": started_at,
                "kwargs": {},
            }
        )
    )

    fresh_failed_at = started_at + timedelta(seconds=8)
    await process_event(
        JobFailedEvent.model_validate(
            {
                "job_id": "job-fail-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-fail-1",
                "error": "new failure",
                "attempt": 2,
                "max_retries": 2,
                "will_retry": False,
                "failed_at": fresh_failed_at,
            }
        )
    )

    # Older/stale failure should be ignored and preserve the existing row state.
    await process_event(
        JobFailedEvent.model_validate(
            {
                "job_id": "job-fail-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-fail-1",
                "error": "stale failure",
                "attempt": 1,
                "max_retries": 2,
                "will_retry": False,
                "failed_at": started_at,
            }
        )
    )

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-fail-1")
        assert row is not None
        assert row.status == "failed"
        assert row.error == "new failure"
        assert as_utc_aware(row.completed_at) == fresh_failed_at
        assert row.attempts == 2


@pytest.mark.asyncio
async def test_job_completed_stale_event_does_not_override_terminal_state(
    sqlite_db,
) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        _started(
            {
                "job_id": "job-complete-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-complete-1",
                "attempt": 2,
                "max_retries": 2,
                "started_at": started_at,
                "kwargs": {},
                "worker_id": "worker-a",
            }
        )
    )

    fresh_completed_at = started_at + timedelta(seconds=5)
    await process_event(
        JobCompletedEvent.model_validate(
            {
                "job_id": "job-complete-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-complete-1",
                "result": {"version": "fresh"},
                "attempt": 2,
                "completed_at": fresh_completed_at,
            }
        )
    )

    stale = await process_event(
        JobCompletedEvent.model_validate(
            {
                "job_id": "job-complete-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-complete-1",
                "result": {"version": "stale"},
                "attempt": 1,
                "completed_at": started_at,
            }
        )
    )
    assert stale is False

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-complete-1")
        assert row is not None
        assert row.status == "complete"
        assert row.result == {"version": "fresh"}
        assert as_utc_aware(row.completed_at) == fresh_completed_at
        assert row.attempts == 2


@pytest.mark.asyncio
async def test_terminal_events_backfill_created_at_when_started_was_missed(
    sqlite_db,
) -> None:
    completed_at = datetime.now(UTC)
    failed_at = completed_at + timedelta(seconds=1)

    completed_applied = await process_event(
        JobCompletedEvent.model_validate(
            {
                "job_id": "job-terminal-created-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-terminal-created-1",
                "result": {"ok": True},
                "attempt": 1,
                "completed_at": completed_at,
            }
        )
    )
    failed_applied = await process_event(
        JobFailedEvent.model_validate(
            {
                "job_id": "job-terminal-created-2",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-terminal-created-2",
                "error": "boom",
                "attempt": 1,
                "max_retries": 0,
                "will_retry": False,
                "failed_at": failed_at,
            }
        )
    )
    assert completed_applied is True
    assert failed_applied is True

    async with sqlite_db.session() as session:
        completed = await session.get(JobHistory, "job-terminal-created-1")
        failed = await session.get(JobHistory, "job-terminal-created-2")
        assert completed is not None
        assert failed is not None
        assert as_utc_aware(completed.created_at) == completed_at
        assert as_utc_aware(failed.created_at) == failed_at


@pytest.mark.asyncio
async def test_job_cancelled_event_persists_terminal_state_and_reason(
    sqlite_db,
) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        _started(
            {
                "job_id": "job-cancel-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-cancel-1",
                "attempt": 1,
                "max_retries": 1,
                "started_at": started_at,
                "kwargs": {},
                "worker_id": "worker-a",
            }
        )
    )

    cancelled_at = started_at + timedelta(seconds=2)
    applied = await process_event(
        JobCancelledEvent.model_validate(
            {
                "job_id": "job-cancel-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-cancel-1",
                "attempt": 1,
                "reason": "Cancelled before execution",
                "cancelled_at": cancelled_at,
            }
        )
    )
    assert applied is True

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-cancel-1")
        assert row is not None
        assert row.status == "cancelled"
        assert row.error == "Cancelled before execution"
        assert as_utc_aware(row.completed_at) == cancelled_at


@pytest.mark.asyncio
async def test_job_cancelled_stale_event_does_not_override_newer_terminal_state(
    sqlite_db,
) -> None:
    base = datetime.now(UTC)
    await process_event(
        JobCompletedEvent.model_validate(
            {
                "job_id": "job-cancel-stale-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-cancel-stale-1",
                "attempt": 2,
                "completed_at": base + timedelta(seconds=5),
            }
        )
    )

    applied = await process_event(
        JobCancelledEvent.model_validate(
            {
                "job_id": "job-cancel-stale-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-cancel-stale-1",
                "attempt": 1,
                "reason": "late cancellation",
                "cancelled_at": base + timedelta(seconds=1),
            }
        )
    )
    assert applied is False

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-cancel-stale-1")
        assert row is not None
        assert row.status == "complete"


@pytest.mark.asyncio
async def test_retrying_event_ignores_stale_payload_and_accepts_newer_payload(
    sqlite_db,
) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        _started(
            {
                "job_id": "job-retry-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-retry-1",
                "attempt": 1,
                "max_retries": 2,
                "started_at": started_at,
                "kwargs": {},
                "worker_id": "worker-a",
            }
        )
    )
    failed_at = started_at + timedelta(seconds=2)
    await process_event(
        JobFailedEvent.model_validate(
            {
                "job_id": "job-retry-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-retry-1",
                "error": "failed once",
                "attempt": 1,
                "max_retries": 2,
                "will_retry": True,
                "failed_at": failed_at,
            }
        )
    )

    stale = await process_event(
        JobRetryingEvent.model_validate(
            {
                "job_id": "job-retry-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-retry-1",
                "error": "stale retry",
                "delay_seconds": 1,
                "current_attempt": 1,
                "next_attempt": 2,
                "retry_at": started_at + timedelta(seconds=1),
            }
        )
    )
    assert stale is False

    applied = await process_event(
        JobRetryingEvent.model_validate(
            {
                "job_id": "job-retry-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-retry-1",
                "error": "retry scheduled",
                "delay_seconds": 1,
                "current_attempt": 1,
                "next_attempt": 2,
                "retry_at": started_at + timedelta(seconds=3),
            }
        )
    )
    assert applied is True

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-retry-1")
        assert row is not None
        assert row.status == "retrying"
        assert row.error == "retry scheduled"
        assert row.attempts == 1


@pytest.mark.asyncio
async def test_progress_and_checkpoint_update_job_state(sqlite_db) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        _started(
            {
                "job_id": "job-progress-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-progress-1",
                "attempt": 1,
                "max_retries": 0,
                "started_at": started_at,
                "kwargs": {},
                "worker_id": "worker-a",
            }
        )
    )

    await process_event(
        JobProgressEvent.model_validate(
            {
                "job_id": "job-progress-1",
                "root_id": "job-progress-1",
                "progress": 0.42,
                "message": "working",
                "updated_at": started_at + timedelta(seconds=2),
            }
        )
    )

    await process_event(
        JobCheckpointEvent.model_validate(
            {
                "job_id": "job-progress-1",
                "root_id": "job-progress-1",
                "state": {"offset": 99, "phase": "download"},
                "checkpointed_at": started_at + timedelta(seconds=3),
            }
        )
    )

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-progress-1")
        assert row is not None
        assert row.progress == pytest.approx(0.42)
        assert row.checkpoint == {"offset": 99, "phase": "download"}
        assert row.checkpoint_at is not None


@pytest.mark.asyncio
async def test_started_event_persists_runtime_fields(
    sqlite_db,
) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        _started(
            {
                "job_id": "job-runtime-meta-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-runtime-meta-1",
                "attempt": 1,
                "max_retries": 0,
                "started_at": started_at,
                "kwargs": {},
                "source": {
                    "type": "cron",
                    "schedule": "* * * * *",
                    "cron_window_at": 1739321000.0,
                    "startup_reconciled": True,
                    "startup_policy": "catch_up",
                },
                "worker_id": "worker-a",
            }
        )
    )

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-runtime-meta-1")
        assert row is not None
        assert row.cron_window_at == 1739321000.0
        assert row.startup_reconciled is True
        assert row.startup_policy == "catch_up"


@pytest.mark.asyncio
async def test_pending_artifacts_promote_when_job_is_recorded(sqlite_db) -> None:
    async with sqlite_db.session() as session:
        repo = ArtifactRepository(session)
        pending = await repo.create_pending(
            job_id="job-artifact-1",
            name="summary",
            artifact_type="json",
            data={"k": "v"},
        )
        assert isinstance(pending.id, str)
        assert pending.id

    await process_event(
        _started(
            {
                "job_id": "job-artifact-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-artifact-1",
                "attempt": 1,
                "max_retries": 0,
                "started_at": datetime.now(UTC),
                "kwargs": {},
                "worker_id": "worker-a",
            }
        )
    )

    async with sqlite_db.session() as session:
        artifact_rows = (await session.execute(Artifact.__table__.select())).all()
        pending_rows = (await session.execute(PendingArtifact.__table__.select())).all()

    assert len(artifact_rows) == 1
    assert len(pending_rows) == 0


@pytest.mark.asyncio
async def test_progress_events_are_coalesced_before_db_write(
    sqlite_db, monkeypatch
) -> None:
    class _Settings:
        event_progress_min_interval_ms = 1000
        event_progress_min_delta = 0.5
        event_progress_force_interval_ms = 5000
        event_progress_state_max_entries = 10000

    monotonic_values = iter([0.0, 0.1, 0.2, 0.3])

    def _fake_monotonic() -> float:
        try:
            return next(monotonic_values)
        except StopIteration:
            return 999.0

    monkeypatch.setattr(event_processing_module, "get_settings", lambda: _Settings())
    monkeypatch.setattr(
        event_processing_module.time,
        "monotonic",
        _fake_monotonic,
    )
    event_processing_module._progress_write_state.clear()  # noqa: SLF001

    started_at = datetime.now(UTC)
    await process_event(
        _started(
            {
                "job_id": "job-progress-coalesce-1",
                "function": "task_key",
                "function_name": "task_name",
                "root_id": "job-progress-coalesce-1",
                "attempt": 1,
                "max_retries": 0,
                "started_at": started_at,
                "kwargs": {},
                "worker_id": "worker-a",
            }
        )
    )

    await process_event(
        JobProgressEvent.model_validate(
            {
                "job_id": "job-progress-coalesce-1",
                "root_id": "job-progress-coalesce-1",
                "progress": 0.1,
                "updated_at": started_at + timedelta(seconds=1),
            }
        )
    )
    await process_event(
        JobProgressEvent.model_validate(
            {
                "job_id": "job-progress-coalesce-1",
                "root_id": "job-progress-coalesce-1",
                "progress": 0.2,
                "updated_at": started_at + timedelta(seconds=2),
            }
        )
    )
    await process_event(
        JobProgressEvent.model_validate(
            {
                "job_id": "job-progress-coalesce-1",
                "root_id": "job-progress-coalesce-1",
                "progress": 0.8,
                "updated_at": started_at + timedelta(seconds=3),
            }
        )
    )

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-progress-coalesce-1")
        assert row is not None
        assert row.progress == pytest.approx(0.8)


def test_progress_force_interval_persists_even_for_small_delta(monkeypatch) -> None:
    class _Settings:
        event_progress_min_interval_ms = 1000
        event_progress_min_delta = 1.0
        event_progress_force_interval_ms = 500
        event_progress_state_max_entries = 10000

    monotonic_values = iter([0.0, 0.1, 0.7, 0.8])

    def _fake_monotonic() -> float:
        try:
            return next(monotonic_values)
        except StopIteration:
            return 999.0

    monkeypatch.setattr(event_processing_module, "get_settings", lambda: _Settings())
    monkeypatch.setattr(
        event_processing_module.time,
        "monotonic",
        _fake_monotonic,
    )
    event_processing_module._progress_write_state.clear()  # noqa: SLF001

    event_processing_module._record_progress_write("job-progress-force-1", 0.0)  # noqa: SLF001

    assert (
        event_processing_module._should_persist_progress(  # noqa: SLF001
            "job-progress-force-1", 0.1
        )
        is False
    )
    assert (
        event_processing_module._should_persist_progress(  # noqa: SLF001
            "job-progress-force-1", 0.15
        )
        is True
    )


@pytest.mark.asyncio
async def test_progress_for_unknown_job_reports_not_applied(sqlite_db) -> None:
    applied = await process_event(
        JobProgressEvent.model_validate(
            {
                "job_id": "job-progress-missing-1",
                "root_id": "job-progress-missing-1",
                "progress": 0.4,
                "updated_at": datetime.now(UTC),
            }
        )
    )
    assert applied is False


@pytest.mark.asyncio
async def test_completed_event_raises_when_database_unavailable(
    monkeypatch,
) -> None:
    def _raise_db():  # type: ignore[no-untyped-def]
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(event_processing_module, "get_database", _raise_db)

    with pytest.raises(RuntimeError, match="db unavailable"):
        await process_event(
            JobCompletedEvent.model_validate(
                {
                    "job_id": "job-complete-unavailable-1",
                    "function": "task_key",
                    "function_name": "task_name",
                    "root_id": "job-complete-unavailable-1",
                    "attempt": 1,
                    "completed_at": datetime.now(UTC),
                }
            )
        )
