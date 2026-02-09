from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from server.db.models import Artifact, JobHistory, PendingArtifact
from server.db.repository import ArtifactRepository
import server.services.event_processing as event_processing_module
from server.services.event_processing import process_event


def _as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
        "metadata": {"a": 1},
        "kwargs": {"x": 1},
    }

    first = await process_event("job.started", payload, "worker-a")
    assert first is True

    stale = dict(payload)
    stale["started_at"] = started_at - timedelta(seconds=1)
    second = await process_event("job.started", stale, "worker-a")
    assert second is False

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-start-1")
        assert row is not None
        assert row.status == "active"
        assert row.attempts == 1
        assert _as_utc_aware(row.started_at) == started_at


@pytest.mark.asyncio
async def test_job_failed_stale_event_does_not_override_terminal_state(sqlite_db) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        "job.started",
        {
            "job_id": "job-fail-1",
            "function": "task_key",
            "function_name": "task_name",
            "root_id": "job-fail-1",
            "attempt": 2,
            "max_retries": 2,
            "started_at": started_at,
            "kwargs": {},
            "metadata": {},
        },
        "worker-a",
    )

    fresh_failed_at = started_at + timedelta(seconds=8)
    await process_event(
        "job.failed",
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
        },
    )

    # Older/stale failure should be ignored and preserve the existing row state.
    await process_event(
        "job.failed",
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
        },
    )

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-fail-1")
        assert row is not None
        assert row.status == "failed"
        assert row.error == "new failure"
        assert _as_utc_aware(row.completed_at) == fresh_failed_at
        assert row.attempts == 2


@pytest.mark.asyncio
async def test_progress_and_checkpoint_update_job_state(sqlite_db) -> None:
    started_at = datetime.now(UTC)
    await process_event(
        "job.started",
        {
            "job_id": "job-progress-1",
            "function": "task_key",
            "function_name": "task_name",
            "root_id": "job-progress-1",
            "attempt": 1,
            "max_retries": 0,
            "started_at": started_at,
            "kwargs": {},
            "metadata": {},
        },
        "worker-a",
    )

    await process_event(
        "job.progress",
        {
            "job_id": "job-progress-1",
            "root_id": "job-progress-1",
            "progress": 0.42,
            "message": "working",
            "updated_at": started_at + timedelta(seconds=2),
        },
    )

    await process_event(
        "job.checkpoint",
        {
            "job_id": "job-progress-1",
            "root_id": "job-progress-1",
            "state": {"offset": 99, "phase": "download"},
            "checkpointed_at": started_at + timedelta(seconds=3),
        },
    )

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-progress-1")
        assert row is not None
        assert row.progress == pytest.approx(0.42)
        assert row.metadata_["checkpoint"] == {"offset": 99, "phase": "download"}
        assert "checkpoint_at" in row.metadata_


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
        assert pending.id > 0

    await process_event(
        "job.started",
        {
            "job_id": "job-artifact-1",
            "function": "task_key",
            "function_name": "task_name",
            "root_id": "job-artifact-1",
            "attempt": 1,
            "max_retries": 0,
            "started_at": datetime.now(UTC),
            "kwargs": {},
            "metadata": {},
        },
        "worker-a",
    )

    async with sqlite_db.session() as session:
        artifact_rows = (await session.execute(Artifact.__table__.select())).all()
        pending_rows = (await session.execute(PendingArtifact.__table__.select())).all()

    assert len(artifact_rows) == 1
    assert len(pending_rows) == 0


@pytest.mark.asyncio
async def test_progress_events_are_coalesced_before_db_write(sqlite_db, monkeypatch) -> None:
    class _Settings:
        event_progress_min_interval_ms = 1000
        event_progress_min_delta = 0.5
        event_progress_force_interval_ms = 5000

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
        "job.started",
        {
            "job_id": "job-progress-coalesce-1",
            "function": "task_key",
            "function_name": "task_name",
            "root_id": "job-progress-coalesce-1",
            "attempt": 1,
            "max_retries": 0,
            "started_at": started_at,
            "kwargs": {},
            "metadata": {},
        },
        "worker-a",
    )

    await process_event(
        "job.progress",
        {
            "job_id": "job-progress-coalesce-1",
            "root_id": "job-progress-coalesce-1",
            "progress": 0.1,
            "updated_at": started_at + timedelta(seconds=1),
        },
    )
    await process_event(
        "job.progress",
        {
            "job_id": "job-progress-coalesce-1",
            "root_id": "job-progress-coalesce-1",
            "progress": 0.2,
            "updated_at": started_at + timedelta(seconds=2),
        },
    )
    await process_event(
        "job.progress",
        {
            "job_id": "job-progress-coalesce-1",
            "root_id": "job-progress-coalesce-1",
            "progress": 0.8,
            "updated_at": started_at + timedelta(seconds=3),
        },
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
