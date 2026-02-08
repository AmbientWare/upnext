from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.exc import IntegrityError

from shared.schemas import (
    ApiInstance,
    ArtifactType,
    CreateArtifactRequest,
    FunctionType,
    WorkerInstance,
    WorkerStats,
)
from shared.events import BatchEventItem, BatchEventRequest

from server.db.repository import JobRepository
import server.routes.apis as apis_route
import server.routes.artifacts as artifacts_route
import server.routes.dashboard as dashboard_route
import server.routes.events as events_route
import server.routes.functions as functions_route
import server.routes.jobs as jobs_route
import server.routes.workers as workers_route


@pytest.mark.asyncio
async def test_jobs_list_get_and_trends_routes_cover_happy_paths(sqlite_db, monkeypatch) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "job-list-1",
                "function": "fn.list",
                "function_name": "list",
                "status": "complete",
                "root_id": "job-list-1",
                "started_at": now - timedelta(seconds=1),
                "completed_at": now,
                "created_at": now - timedelta(minutes=1),
            }
        )

    monkeypatch.setattr(jobs_route, "get_database", lambda: sqlite_db)

    listed = await jobs_route.list_jobs(
        function="fn.list",
        status=None,
        worker_id=None,
        after=None,
        before=None,
        limit=100,
        offset=0,
    )
    assert listed.total == 1
    assert listed.jobs[0].id == "job-list-1"

    fetched = await jobs_route.get_job("job-list-1")
    assert fetched.id == "job-list-1"
    assert fetched.duration_ms == 1000

    stats = await jobs_route.get_job_stats(function="fn.list", after=None, before=None)
    assert stats.total == 1
    assert stats.success_count == 1

    trends = await jobs_route.get_job_trends(hours=2, function="fn.list", type=None)
    assert len(trends.hourly) == 2
    assert sum(hour.complete for hour in trends.hourly) == 1
    assert sum(hour.failed for hour in trends.hourly) == 0


@pytest.mark.asyncio
async def test_jobs_routes_handle_missing_database_and_not_found(monkeypatch) -> None:
    def no_db():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(jobs_route, "get_database", no_db)

    listed = await jobs_route.list_jobs(
        function=None,
        status=None,
        worker_id=None,
        after=None,
        before=None,
        limit=100,
        offset=0,
    )
    assert listed.total == 0
    assert listed.jobs == []

    stats = await jobs_route.get_job_stats(function=None, after=None, before=None)
    assert stats.total == 0
    assert stats.success_rate == 100.0

    trends = await jobs_route.get_job_trends(hours=3, function=None, type=None)
    assert len(trends.hourly) == 3

    with pytest.raises(HTTPException, match="Job not found") as timeline_exc:
        await jobs_route.get_job_timeline("missing")
    assert timeline_exc.value.status_code == 404

    with pytest.raises(HTTPException, match="Job not found") as job_exc:
        await jobs_route.get_job("missing")
    assert job_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_jobs_cancel_and_retry_routes_return_not_implemented() -> None:
    with pytest.raises(HTTPException, match="not implemented yet") as cancel_exc:
        await jobs_route.cancel_job("job-123")
    assert cancel_exc.value.status_code == 501
    assert "job-123" in cancel_exc.value.detail

    with pytest.raises(HTTPException, match="not implemented yet") as retry_exc:
        await jobs_route.retry_job("job-456")
    assert retry_exc.value.status_code == 501
    assert "job-456" in retry_exc.value.detail


@pytest.mark.asyncio
async def test_jobs_timeline_returns_recursive_subtree(sqlite_db) -> None:
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "root-job",
                "function": "fn.root",
                "function_name": "root",
                "status": "active",
                "root_id": "root-job",
                "created_at": datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
            }
        )
        await repo.record_job(
            {
                "job_id": "child-job",
                "function": "fn.child",
                "function_name": "child",
                "status": "complete",
                "parent_id": "root-job",
                "root_id": "root-job",
                "created_at": datetime(2026, 2, 8, 12, 1, tzinfo=UTC),
            }
        )

    out = await jobs_route.get_job_timeline("root-job")
    assert out.total == 2
    assert [job.id for job in out.jobs] == ["root-job", "child-job"]


@pytest.mark.asyncio
async def test_functions_route_aggregates_defs_stats_and_workers(sqlite_db, monkeypatch) -> None:
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "fn-job-1",
                "function": "task_key",
                "function_name": "my_task",
                "status": "complete",
                "root_id": "fn-job-1",
                "started_at": datetime(2026, 2, 8, 10, 0, tzinfo=UTC),
                "completed_at": datetime(2026, 2, 8, 10, 0, 1, tzinfo=UTC),
                "created_at": datetime.now(UTC),
            }
        )

    async def fake_defs() -> dict:
        return {
            "task_key": {
                "key": "task_key",
                "name": "my_task",
                "type": FunctionType.TASK,
                "timeout": 30,
                "max_retries": 1,
                "retry_delay": 1,
            }
        }

    async def fake_workers() -> list[WorkerInstance]:
        return [
            WorkerInstance(
                id="worker-1",
                worker_name="worker-a",
                started_at=datetime.now(UTC).isoformat(),
                last_heartbeat=datetime.now(UTC).isoformat(),
                functions=["task_key"],
                function_names={"task_key": "my_task"},
                concurrency=1,
                active_jobs=0,
                jobs_processed=0,
                jobs_failed=0,
                hostname="host-a",
            )
        ]

    monkeypatch.setattr(functions_route, "get_function_definitions", fake_defs)
    monkeypatch.setattr(functions_route, "list_worker_instances", fake_workers)
    monkeypatch.setattr(functions_route, "get_database", lambda: sqlite_db)

    out = await functions_route.list_functions(type=None)
    assert out.total == 1
    fn = out.functions[0]
    assert fn.key == "task_key"
    assert fn.active is True
    assert fn.runs_24h == 1
    assert fn.success_rate == 100.0
    assert fn.workers == ["worker-a"]


@pytest.mark.asyncio
async def test_workers_route_includes_defs_and_instance_only_workers(monkeypatch) -> None:
    async def fake_defs() -> dict:
        return {
            "defined-worker": {
                "name": "defined-worker",
                "functions": ["fn.defined"],
                "function_names": {"fn.defined": "defined"},
                "concurrency": 2,
            }
        }

    async def fake_instances() -> list[WorkerInstance]:
        return [
            WorkerInstance(
                id="w-1",
                worker_name="defined-worker",
                started_at=datetime.now(UTC).isoformat(),
                last_heartbeat=datetime.now(UTC).isoformat(),
                functions=["fn.defined"],
                function_names={"fn.defined": "defined"},
                concurrency=2,
                active_jobs=0,
                jobs_processed=0,
                jobs_failed=0,
                hostname=None,
            ),
            WorkerInstance(
                id="w-2",
                worker_name="ephemeral-worker",
                started_at=datetime.now(UTC).isoformat(),
                last_heartbeat=datetime.now(UTC).isoformat(),
                functions=["fn.ephemeral"],
                function_names={"fn.ephemeral": "ephemeral"},
                concurrency=1,
                active_jobs=0,
                jobs_processed=0,
                jobs_failed=0,
                hostname=None,
            ),
        ]

    monkeypatch.setattr(workers_route, "get_worker_definitions", fake_defs)
    monkeypatch.setattr(workers_route, "list_worker_instances", fake_instances)

    out = await workers_route.list_workers_route()
    names = {w.name for w in out.workers}
    assert names == {"defined-worker", "ephemeral-worker"}


@pytest.mark.asyncio
async def test_dashboard_returns_defaults_when_database_unavailable(monkeypatch) -> None:
    def no_db():
        raise RuntimeError("db unavailable")

    async def fake_active_count() -> int:
        return 3

    async def fake_worker_stats() -> WorkerStats:
        return WorkerStats(total=0)

    class FakeReader:
        async def get_summary(self) -> dict[str, float]:
            return {"requests_24h": 0, "avg_latency_ms": 0, "error_rate": 0}

    async def fake_reader() -> FakeReader:
        return FakeReader()

    monkeypatch.setattr(dashboard_route, "get_database", no_db)
    monkeypatch.setattr(dashboard_route, "get_active_job_count", fake_active_count)
    monkeypatch.setattr(dashboard_route, "get_worker_stats", fake_worker_stats)
    monkeypatch.setattr(dashboard_route, "get_metrics_reader", fake_reader)

    out = await dashboard_route.get_dashboard_stats()
    assert out.runs.total_24h == 0
    assert out.runs.active_count == 3
    assert out.recent_runs == []


@pytest.mark.asyncio
async def test_create_artifact_fk_race_returns_queued(sqlite_db, monkeypatch) -> None:
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "job-art-race",
                "function": "fn",
                "function_name": "fn",
                "status": "active",
                "root_id": "job-art-race",
                "created_at": datetime.now(UTC),
            }
        )

    async def raise_integrity(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise IntegrityError("insert", {}, Exception("fk race"))

    monkeypatch.setattr(artifacts_route.ArtifactRepository, "create", raise_integrity)

    response = Response()
    out = await artifacts_route.create_artifact(
        "job-art-race",
        CreateArtifactRequest(name="summary", type=ArtifactType.JSON, data={"x": 1}),
        response,
    )

    assert response.status_code == 202
    assert out.job_id == "job-art-race"


@pytest.mark.asyncio
async def test_event_batch_reports_processed_and_errors(monkeypatch) -> None:
    async def fake_process_event(event_type: str, data: dict, worker_id: str | None) -> bool:
        if event_type == "bad.event":
            raise RuntimeError("bad")
        return event_type != "ignored.event"

    monkeypatch.setattr(events_route, "process_event", fake_process_event)

    req = BatchEventRequest(
        events=[
            BatchEventItem(
                type="job.started",
                job_id="a",
                worker_id="w",
                timestamp=1,
                data={},
            ),
            BatchEventItem(
                type="ignored.event",
                job_id="b",
                worker_id="w",
                timestamp=2,
                data={},
            ),
            BatchEventItem(
                type="bad.event",
                job_id="c",
                worker_id="w",
                timestamp=3,
                data={},
            ),
        ]
    )

    out = await events_route.ingest_batch(req)
    assert out.processed == 1
    assert out.errors == 1


@pytest.mark.asyncio
async def test_apis_route_merges_tracked_and_active_instances(monkeypatch) -> None:
    class FakeMetricsReader:
        async def get_apis(self) -> list[dict]:
            return [
                {
                    "name": "tracked-api",
                    "endpoint_count": 1,
                    "requests_24h": 10,
                    "avg_latency_ms": 20,
                    "error_rate": 0,
                    "requests_per_min": 0.5,
                }
            ]

    async def fake_reader() -> FakeMetricsReader:
        return FakeMetricsReader()

    async def fake_instances() -> list[ApiInstance]:
        return [
            ApiInstance(
                id="api-1",
                api_name="tracked-api",
                started_at=datetime.now(UTC).isoformat(),
                last_heartbeat=datetime.now(UTC).isoformat(),
                host="0.0.0.0",
                port=8080,
                endpoints=["GET:/x"],
                hostname=None,
            ),
            ApiInstance(
                id="api-2",
                api_name="instance-only-api",
                started_at=datetime.now(UTC).isoformat(),
                last_heartbeat=datetime.now(UTC).isoformat(),
                host="0.0.0.0",
                port=8081,
                endpoints=["GET:/y"],
                hostname=None,
            ),
        ]

    monkeypatch.setattr(apis_route, "get_metrics_reader", fake_reader)
    monkeypatch.setattr(apis_route, "list_api_instances", fake_instances)

    out = await apis_route.list_apis()
    names = {api.name for api in out.apis}
    assert names == {"tracked-api", "instance-only-api"}
    tracked = next(api for api in out.apis if api.name == "tracked-api")
    assert tracked.active is True
    assert tracked.instance_count == 1
