from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import permutations
from time import perf_counter

import pytest
import server.routes.jobs.jobs_root as jobs_root_route
import server.services.events.processing as event_processing_module
from pydantic import ValidationError
from server.db.repositories import ArtifactRepository, JobRepository
from server.db.tables import Artifact, JobHistory, PendingArtifact
from server.services.events import process_event
from shared.contracts import (
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobStartedEvent,
    SSEJobEvent,
)


@pytest.mark.contract
def test_event_model_contract_requires_lineage_fields() -> None:
    now = datetime.now(UTC)

    JobStartedEvent(
        job_id="job-1",
        function="fn",
        function_name="fn",
        root_id="job-1",
        kwargs={},
        attempt=1,
        max_retries=0,
        started_at=now,
    )
    JobCompletedEvent(
        job_id="job-1",
        function="fn",
        function_name="fn",
        root_id="job-1",
        attempt=1,
        completed_at=now,
    )
    JobFailedEvent(
        job_id="job-1",
        function="fn",
        function_name="fn",
        root_id="job-1",
        error="boom",
        attempt=1,
        max_retries=0,
        failed_at=now,
    )

    with pytest.raises(ValidationError):
        JobStartedEvent(  # type: ignore[call-arg]
            job_id="job-1",
            function="fn",
            function_name="fn",
            # missing root_id should fail contract
            kwargs={},
            attempt=1,
            max_retries=0,
            started_at=now,
        )


@pytest.mark.contract
def test_sse_contract_excludes_sensitive_fields() -> None:
    event = SSEJobEvent(
        type="job.failed",
        job_id="job-safe",
        worker_id="worker-1",
        function="fn",
        function_name="fn",
        root_id="job-safe",
        error="fail",
        attempt=1,
        max_retries=0,
        failed_at=datetime.now(UTC),
    )
    dumped = event.model_dump(exclude_none=True)
    assert dumped["job_id"] == "job-safe"
    assert "kwargs" not in dumped
    assert "traceback" not in dumped


@pytest.mark.asyncio
async def test_event_replay_invariant_same_final_state_for_permuted_sequences(
    sqlite_db,
) -> None:
    base = datetime.now(UTC)

    events = [
        (
            "job.started",
            {
                "function": "fn",
                "function_name": "fn",
                "root_id": "ROOT",
                "attempt": 1,
                "max_retries": 0,
                "started_at": base,
                "kwargs": {},
            },
        ),
        (
            "job.progress",
            {
                "root_id": "ROOT",
                "progress": 0.6,
                "message": "mid",
                "updated_at": base + timedelta(seconds=1),
            },
        ),
        (
            "job.completed",
            {
                "function": "fn",
                "function_name": "fn",
                "root_id": "ROOT",
                "attempt": 1,
                "completed_at": base + timedelta(seconds=2),
                "duration_ms": 2000,
                "result": {"ok": True},
            },
        ),
    ]

    fingerprints: set[tuple[str, float, int]] = set()

    for idx, order in enumerate(permutations(events), start=1):
        job_id = f"replay-{idx}"
        root_id = job_id
        for event_type, payload in order:
            materialized = {**payload, "job_id": job_id, "root_id": root_id}
            if event_type == "job.started":
                await process_event(
                    JobStartedEvent.model_validate(
                        {**materialized, "worker_id": "worker-replay"}
                    )
                )
            elif event_type == "job.progress":
                await process_event(JobProgressEvent.model_validate(materialized))
            elif event_type == "job.completed":
                await process_event(JobCompletedEvent.model_validate(materialized))
            else:
                raise AssertionError(f"Unexpected event type in test: {event_type}")

        async with sqlite_db.session() as session:
            row = await session.get(JobHistory, job_id)
            assert row is not None
            fingerprints.add((row.status, row.progress, row.attempts))

    assert len(fingerprints) == 1
    assert next(iter(fingerprints))[0] == "complete"


@pytest.mark.asyncio
async def test_outage_then_replay_recovers_without_duplicates(
    sqlite_db, monkeypatch
) -> None:
    payload = {
        "job_id": "outage-job",
        "function": "fn",
        "function_name": "fn",
        "root_id": "outage-job",
        "attempt": 1,
        "max_retries": 0,
        "started_at": datetime.now(UTC),
        "kwargs": {},
    }

    calls = {"n": 0}

    def flaky_get_database():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db down")
        return sqlite_db

    monkeypatch.setattr(event_processing_module, "get_database", flaky_get_database)

    # First processing during outage fails and should be retried later.
    with pytest.raises(RuntimeError, match="db down"):
        await process_event(
            JobStartedEvent.model_validate({**payload, "worker_id": "worker"})
        )

    # Replay after DB recovery should persist exactly one row.
    assert (
        await process_event(
            JobStartedEvent.model_validate({**payload, "worker_id": "worker"})
        )
        is True
    )

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "outage-job")
        assert row is not None
        assert row.status == "active"


@pytest.mark.asyncio
async def test_job_trends_route_zero_fills_missing_hours(
    sqlite_db,
) -> None:
    now = datetime.now(UTC)

    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "trend-hour-1",
                "function": "fn.trend",
                "function_name": "trend",
                "status": "complete",
                "root_id": "trend-hour-1",
                "created_at": now - timedelta(hours=2),
            }
        )

    out = await jobs_root_route.get_job_trends(
        hours=4, function="fn.trend", type=None, db=sqlite_db
    )

    assert len(out.hourly) == 4
    hours = [item.hour for item in out.hourly]
    assert hours == sorted(hours)
    assert sum(item.complete for item in out.hourly) == 1
    assert sum(item.failed for item in out.hourly) == 0
    assert any(
        item.complete == 0
        and item.failed == 0
        and item.retrying == 0
        and item.active == 0
        for item in out.hourly
    )


@pytest.mark.performance
@pytest.mark.asyncio
async def test_large_subtree_query_stays_within_budget(sqlite_db) -> None:
    root_id = "perf-root"
    created = datetime.now(UTC)

    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": root_id,
                "function": "fn.perf",
                "function_name": "perf",
                "status": "active",
                "root_id": root_id,
                "created_at": created,
            }
        )
        parent = root_id
        # Build a deep but realistic chain.
        for i in range(1, 400):
            job_id = f"perf-{i}"
            await repo.record_job(
                {
                    "job_id": job_id,
                    "function": "fn.perf",
                    "function_name": "perf",
                    "status": "complete",
                    "parent_id": parent,
                    "root_id": root_id,
                    "created_at": created + timedelta(milliseconds=i),
                }
            )
            parent = job_id

    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        start = perf_counter()
        rows = await repo.list_job_subtree(root_id)
        elapsed = perf_counter() - start

    assert len(rows) == 400
    # Keep a practical local budget while still catching severe regressions.
    assert elapsed < 3.0


@pytest.mark.asyncio
async def test_started_event_time_comparison_handles_naive_and_aware_datetimes(
    sqlite_db,
) -> None:
    started_at_aware = datetime.now(UTC).replace(microsecond=0)
    started_at_naive = started_at_aware.replace(tzinfo=None)

    applied = await process_event(
        JobStartedEvent.model_validate(
            {
                "job_id": "job-time-1",
                "function": "fn.time",
                "function_name": "time",
                "root_id": "job-time-1",
                "attempt": 1,
                "max_retries": 0,
                "started_at": started_at_aware,
                "kwargs": {},
                "worker_id": "worker-time",
            }
        )
    )
    assert applied is True

    # Same timestamp but naive form should still be treated as duplicate.
    duplicate = await process_event(
        JobStartedEvent.model_validate(
            {
                "job_id": "job-time-1",
                "function": "fn.time",
                "function_name": "time",
                "root_id": "job-time-1",
                "attempt": 1,
                "max_retries": 0,
                "started_at": started_at_naive,
                "kwargs": {},
                "worker_id": "worker-time",
            }
        )
    )
    assert duplicate is False

    async with sqlite_db.session() as session:
        row = await session.get(JobHistory, "job-time-1")
        assert row is not None
        assert row.attempts == 1


@pytest.mark.asyncio
async def test_pending_artifact_promotion_preserves_all_rows_without_orphans(
    sqlite_db,
) -> None:
    async with sqlite_db.session() as session:
        artifacts = ArtifactRepository(session)
        await artifacts.create_pending(
            job_id="artifact-life-1",
            name="summary",
            artifact_type="json",
            data={"value": 1},
        )
        await artifacts.create_pending(
            job_id="artifact-life-1",
            name="summary",
            artifact_type="json",
            data={"value": 1},
        )

    await process_event(
        JobStartedEvent.model_validate(
            {
                "job_id": "artifact-life-1",
                "function": "fn.artifact",
                "function_name": "artifact",
                "root_id": "artifact-life-1",
                "attempt": 1,
                "max_retries": 0,
                "started_at": datetime.now(UTC),
                "kwargs": {},
                "worker_id": "worker-artifact",
            }
        )
    )

    async with sqlite_db.session() as session:
        artifact_rows = (await session.execute(Artifact.__table__.select())).all()
        pending_rows = (await session.execute(PendingArtifact.__table__.select())).all()

    assert len(artifact_rows) == 2
    assert len(pending_rows) == 0
