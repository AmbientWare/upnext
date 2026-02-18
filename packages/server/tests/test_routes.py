from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import AsyncIterator, cast

import pytest
import server.routes.apis as apis_route
import server.routes.apis.apis_root as apis_root_route
import server.routes.artifacts.artifacts_root as artifacts_root_route
import server.routes.artifacts.artifacts_stream as artifacts_stream_route
import server.routes.dashboard as dashboard_route
import server.routes.functions as functions_route
import server.routes.functions_utils as functions_utils_route
import server.routes.health as health_route
import server.routes.jobs as jobs_route
import server.routes.jobs.jobs_root as jobs_root_route
import server.routes.jobs.jobs_stream as jobs_stream_route
import server.routes.workers as workers_route
import server.routes.workers.workers_root as workers_root_route
import server.routes.workers.workers_stream as workers_stream_route
import server.services.apis.tracking as api_tracking_module
from fastapi import HTTPException, Response
from server.db.repositories import JobRepository
from server.services.jobs.metrics import QueuedJobSnapshot
from shared.contracts import (
    ApiInstance,
    ArtifactType,
    CreateArtifactRequest,
    FunctionConfig,
    FunctionType,
    JobTrendHour,
    JobTrendsResponse,
    WorkerInstance,
    WorkerStats,
)
from shared.domain.jobs import Job
from shared.keys import ARTIFACT_EVENTS_STREAM
from shared.keys.workers import FUNCTION_KEY_PREFIX
from sqlalchemy.exc import IntegrityError


@pytest.fixture(autouse=True)
def _clear_health_metrics_cache() -> None:
    health_route.clear_health_metrics_cache()


@pytest.mark.asyncio
async def test_jobs_list_get_and_trends_routes_cover_happy_paths(
    sqlite_db, monkeypatch
) -> None:
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

    listed = await jobs_route.list_jobs(
        function="fn.list",
        status=None,
        worker_id=None,
        after=None,
        before=None,
        limit=100,
        cursor=None,
        db=sqlite_db,
    )
    assert listed.total == 1
    assert listed.jobs[0].id == "job-list-1"

    fetched = await jobs_route.get_job("job-list-1", db=sqlite_db)
    assert fetched.id == "job-list-1"
    assert fetched.duration_ms == 1000

    stats = await jobs_route.get_job_stats(
        function="fn.list", after=None, before=None, db=sqlite_db
    )
    assert stats.total == 1
    assert stats.success_count == 1
    assert stats.avg_duration_ms == pytest.approx(1000.0, abs=0.1)

    trends = await jobs_route.get_job_trends(
        hours=2, function="fn.list", type=None, db=sqlite_db
    )
    assert len(trends.hourly) == 2
    assert sum(hour.complete for hour in trends.hourly) == 1
    assert sum(hour.failed for hour in trends.hourly) == 0


@pytest.mark.asyncio
async def test_jobs_routes_handle_missing_database_and_not_found(monkeypatch) -> None:
    import server.routes.depends as depends_module
    from server.routes.depends import require_database

    def _no_db():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(depends_module, "get_database", _no_db)

    with pytest.raises(HTTPException) as list_exc:
        require_database()
    assert list_exc.value.status_code == 503


@pytest.mark.asyncio
async def test_health_route_includes_alert_metrics(monkeypatch) -> None:
    class _SessionStub:
        async def __aenter__(self) -> "_SessionStub":
            return self

        async def __aexit__(self, *_args) -> None:  # type: ignore[no-untyped-def]
            return None

        async def execute(self, _query) -> None:  # type: ignore[no-untyped-def]
            return None

    class _DatabaseStub:
        def session(self) -> _SessionStub:
            return _SessionStub()

    class _RedisStub:
        async def ping(self) -> bool:
            return True

    class _SettingsStub:
        version = "0.0.1"
        redis_url = "redis://localhost:6379"

    async def _get_redis() -> _RedisStub:
        return _RedisStub()

    monkeypatch.setattr(health_route, "get_settings", lambda: _SettingsStub())
    monkeypatch.setattr(health_route, "get_database", lambda: _DatabaseStub())
    monkeypatch.setattr(health_route, "get_redis", _get_redis)
    monkeypatch.setattr(
        health_route,
        "get_alert_delivery_stats",
        lambda: {"sent": 2, "failures": 1},
    )

    payload = await health_route.health_check()
    assert payload.status == "ok"
    assert payload.metrics.alerts.sent == 2
    assert payload.metrics.readiness.database.status == "ok"
    assert payload.metrics.readiness.redis.status == "ok"

    ready_response = Response()
    ready_payload = await health_route.readiness_check(ready_response)
    assert ready_response.status_code == 200
    assert ready_payload.status == "ok"


@pytest.mark.asyncio
async def test_readiness_route_returns_503_when_dependencies_fail(monkeypatch) -> None:
    class _SettingsStub:
        version = "0.0.1"
        redis_url = "redis://localhost:6379"

    async def _get_redis():
        raise RuntimeError("redis unavailable")

    def _get_database():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(health_route, "get_settings", lambda: _SettingsStub())
    monkeypatch.setattr(health_route, "get_database", _get_database)
    monkeypatch.setattr(health_route, "get_redis", _get_redis)

    liveness = await health_route.health_check()
    assert liveness.status == "degraded"
    assert liveness.metrics.readiness.database.status == "error"
    assert liveness.metrics.readiness.redis.status == "error"

    ready_response = Response()
    readiness = await health_route.readiness_check(ready_response)
    assert ready_response.status_code == 503
    assert readiness.status == "degraded"


@pytest.mark.asyncio
async def test_readiness_requires_redis_in_production(monkeypatch) -> None:
    class _SessionStub:
        async def __aenter__(self) -> "_SessionStub":
            return self

        async def __aexit__(self, *_args) -> None:  # type: ignore[no-untyped-def]
            return None

        async def execute(self, _query) -> None:  # type: ignore[no-untyped-def]
            return None

    class _DatabaseStub:
        def session(self) -> _SessionStub:
            return _SessionStub()

    class _SettingsStub:
        version = "0.0.1"
        redis_url = None
        is_production = True
        readiness_require_redis = False

    monkeypatch.setattr(health_route, "get_settings", lambda: _SettingsStub())
    monkeypatch.setattr(health_route, "get_database", lambda: _DatabaseStub())

    liveness = await health_route.health_check()
    assert liveness.status == "degraded"
    assert liveness.metrics.readiness.database.status == "ok"
    assert liveness.metrics.readiness.redis.status == "error"

    ready_response = Response()
    readiness = await health_route.readiness_check(ready_response)
    assert ready_response.status_code == 503
    assert readiness.status == "degraded"


@pytest.mark.asyncio
async def test_readiness_allows_missing_redis_in_development(monkeypatch) -> None:
    class _SessionStub:
        async def __aenter__(self) -> "_SessionStub":
            return self

        async def __aexit__(self, *_args) -> None:  # type: ignore[no-untyped-def]
            return None

        async def execute(self, _query) -> None:  # type: ignore[no-untyped-def]
            return None

    class _DatabaseStub:
        def session(self) -> _SessionStub:
            return _SessionStub()

    class _SettingsStub:
        version = "0.0.1"
        redis_url = None
        is_production = False
        readiness_require_redis = False

    monkeypatch.setattr(health_route, "get_settings", lambda: _SettingsStub())
    monkeypatch.setattr(health_route, "get_database", lambda: _DatabaseStub())

    liveness = await health_route.health_check()
    assert liveness.status == "ok"
    assert liveness.metrics.readiness.database.status == "ok"
    assert liveness.metrics.readiness.redis.status == "skipped"

    ready_response = Response()
    readiness = await health_route.readiness_check(ready_response)
    assert ready_response.status_code == 200
    assert readiness.status == "ok"


@pytest.mark.asyncio
async def test_job_trends_stream_emits_initial_and_update_frames(monkeypatch) -> None:
    class _RedisStub:
        async def xread(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return [
                (
                    "upnext:status:events",
                    [("1000-0", {"type": "job.started", "data": "{}"})],
                )
            ]

    class _RequestStub:
        def __init__(self) -> None:
            self._calls = 0

        async def is_disconnected(self) -> bool:
            self._calls += 1
            return self._calls > 2

    async def _get_redis() -> _RedisStub:
        return _RedisStub()

    call_count = {"value": 0}

    async def _get_job_trends(
        hours: int = 24,
        function: str | None = None,
        type: str | None = None,
    ) -> JobTrendsResponse:
        _ = hours, function, type
        call_count["value"] += 1
        return JobTrendsResponse(
            hourly=[
                JobTrendHour(
                    hour="2026-02-09T12:00:00Z",
                    complete=call_count["value"],
                )
            ]
        )

    monkeypatch.setattr(jobs_stream_route, "get_redis", _get_redis)
    monkeypatch.setattr(jobs_stream_route, "get_job_trends", _get_job_trends)

    response = await jobs_route.stream_job_trends(_RequestStub())
    body = cast(AsyncIterator[str], response.body_iterator.__aiter__())
    open_frame = await anext(body)
    first_snapshot_frame = await anext(body)
    second_snapshot_frame = await anext(body)

    assert open_frame == "event: open\ndata: connected\n\n"

    first = json.loads(first_snapshot_frame.removeprefix("data: ").strip())
    second = json.loads(second_snapshot_frame.removeprefix("data: ").strip())
    assert first["type"] == "jobs.trends.snapshot"
    assert first["trends"]["hourly"][0]["complete"] == 1
    assert second["type"] == "jobs.trends.snapshot"
    assert second["trends"]["hourly"][0]["complete"] == 2


@pytest.mark.asyncio
async def test_job_trends_stream_ignores_progress_events(monkeypatch) -> None:
    class _RedisStub:
        def __init__(self) -> None:
            self._call = 0

        async def xread(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            self._call += 1
            if self._call == 1:
                return [
                    (
                        "upnext:status:events",
                        [
                            (
                                "1000-0",
                                {
                                    "type": "job.progress",
                                    "data": json.dumps(
                                        {"function": "fn.list", "progress": 0.5}
                                    ),
                                },
                            )
                        ],
                    )
                ]
            return [
                (
                    "upnext:status:events",
                    [
                        (
                            "1001-0",
                            {
                                "type": "job.started",
                                "data": json.dumps({"function": "fn.list"}),
                            },
                        )
                    ],
                )
            ]

    class _RequestStub:
        def __init__(self) -> None:
            self._calls = 0

        async def is_disconnected(self) -> bool:
            self._calls += 1
            return self._calls > 3

    async def _get_redis() -> _RedisStub:
        return _RedisStub()

    call_count = {"value": 0}

    async def _get_job_trends(
        hours: int = 24,
        function: str | None = None,
        type: str | None = None,
    ) -> JobTrendsResponse:
        _ = hours, function, type
        call_count["value"] += 1
        return JobTrendsResponse(
            hourly=[
                JobTrendHour(
                    hour="2026-02-09T12:00:00Z",
                    complete=call_count["value"],
                )
            ]
        )

    monkeypatch.setattr(jobs_stream_route, "get_redis", _get_redis)
    monkeypatch.setattr(jobs_stream_route, "get_job_trends", _get_job_trends)

    response = await jobs_route.stream_job_trends(_RequestStub())
    body = cast(AsyncIterator[str], response.body_iterator.__aiter__())
    open_frame = await anext(body)
    first_snapshot_frame = await anext(body)
    second_snapshot_frame = await anext(body)

    assert open_frame == "event: open\ndata: connected\n\n"

    first = json.loads(first_snapshot_frame.removeprefix("data: ").strip())
    second = json.loads(second_snapshot_frame.removeprefix("data: ").strip())
    assert first["type"] == "jobs.trends.snapshot"
    assert first["trends"]["hourly"][0]["complete"] == 1
    assert second["type"] == "jobs.trends.snapshot"
    assert second["trends"]["hourly"][0]["complete"] == 2
    # Initial snapshot + one update from job.started. job.progress is ignored.
    assert call_count["value"] == 2


@pytest.mark.asyncio
async def test_jobs_cancel_and_retry_routes_operate_on_redis_queue(
    fake_redis, monkeypatch
) -> None:
    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(jobs_root_route, "get_redis", _get_redis)

    queued = Job(id="job-123", function="fn.cancel", function_name="cancel")
    queued.mark_queued("queued for cancellation test")
    queued_key = "upnext:job:fn.cancel:job-123"
    queued_payload = queued.to_json().encode()
    await fake_redis.setex(queued_key, 86_400, queued_payload)
    await fake_redis.setex("upnext:job_index:job-123", 86_400, queued_key)
    await fake_redis.xadd(
        "upnext:fn:fn.cancel:stream",
        {
            "job_id": queued.id,
            "function": queued.function,
            "data": queued.to_json(),
        },
    )

    failed = Job(id="job-456", function="fn.retry", function_name="retry")
    failed.mark_failed("boom")
    failed.key = "retry-key-456"
    await fake_redis.setex("upnext:result:job-456", 3_600, failed.to_json().encode())

    cancel_out = await jobs_route.cancel_job("job-123")
    assert cancel_out.job_id == "job-123"
    assert cancel_out.cancelled is True
    assert await fake_redis.get(queued_key) is None
    cancelled_result = await fake_redis.get("upnext:result:job-123")
    assert cancelled_result is not None
    assert Job.from_json(cancelled_result.decode()).status.value == "cancelled"

    retry_out = await jobs_route.retry_job("job-456")
    assert retry_out.job_id == "job-456"
    assert retry_out.retried is True
    retried_job = await fake_redis.get("upnext:job:fn.retry:job-456")
    assert retried_job is not None
    assert Job.from_json(retried_job.decode()).status.value == "queued"
    queued_messages = await fake_redis.xrange("upnext:fn:fn.retry:stream", count=10)
    assert any(row[1].get(b"job_id") == b"job-456" for row in queued_messages)
    assert await fake_redis.sismember("upnext:fn:fn.retry:dedup", "retry-key-456") == 1


@pytest.mark.asyncio
async def test_jobs_cancel_and_retry_routes_validate_status_and_presence(
    fake_redis, monkeypatch
) -> None:
    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(jobs_root_route, "get_redis", _get_redis)

    with pytest.raises(HTTPException, match="Job not found") as not_found:
        await jobs_route.cancel_job("missing")
    assert not_found.value.status_code == 404

    active = Job(id="job-active", function="fn.active", function_name="active")
    active.mark_queued()
    await fake_redis.setex(
        "upnext:job:fn.active:job-active", 86_400, active.to_json().encode()
    )
    await fake_redis.setex(
        "upnext:job_index:job-active", 86_400, "upnext:job:fn.active:job-active"
    )

    with pytest.raises(HTTPException, match="cannot be retried") as conflict:
        await jobs_route.retry_job("job-active")
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_retry_route_rejects_active_idempotency_key(
    fake_redis, monkeypatch
) -> None:
    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(jobs_root_route, "get_redis", _get_redis)

    failed = Job(id="job-idempotency", function="fn.retry", function_name="retry")
    failed.mark_failed("boom")
    failed.key = "shared-key"
    await fake_redis.setex(
        "upnext:result:job-idempotency",
        3_600,
        failed.to_json().encode(),
    )
    await fake_redis.sadd("upnext:fn:fn.retry:dedup", "shared-key")

    with pytest.raises(HTTPException, match="idempotency key 'shared-key'") as conflict:
        await jobs_route.retry_job("job-idempotency")
    assert conflict.value.status_code == 409


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

    out = await jobs_route.get_job_timeline("root-job", db=sqlite_db)
    assert out.total == 2
    assert [job.id for job in out.jobs] == ["root-job", "child-job"]


@pytest.mark.asyncio
async def test_functions_route_aggregates_defs_stats_and_workers(
    sqlite_db, monkeypatch
) -> None:
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

    async def fake_defs() -> dict[str, FunctionConfig]:
        return {
            "task_key": FunctionConfig(
                key="task_key",
                name="my_task",
                type=FunctionType.TASK,
                timeout=30,
                max_retries=1,
                retry_delay=1,
            )
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

    out = await functions_route.list_functions(type=None, db=sqlite_db)
    assert out.total == 1
    fn = out.functions[0]
    assert fn.key == "task_key"
    assert fn.active is True
    assert fn.runs_24h == 1
    assert fn.success_rate == 100.0
    assert fn.workers == ["worker-a"]


@pytest.mark.asyncio
async def test_functions_pause_and_resume_routes_persist_pause_state(
    fake_redis, monkeypatch
) -> None:
    function_key = "fn.pause"
    redis_key = f"{FUNCTION_KEY_PREFIX}:{function_key}"
    await fake_redis.set(
        redis_key,
        json.dumps(
            {
                "key": function_key,
                "name": "Pause Test",
                "type": "task",
            }
        ),
    )

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(functions_utils_route, "get_redis", _get_redis)

    paused = await functions_route.pause_function(function_key)
    assert paused == {"key": function_key, "paused": True}
    raw_after_pause = await fake_redis.get(redis_key)
    assert raw_after_pause is not None
    assert json.loads(raw_after_pause.decode())["paused"] is True

    resumed = await functions_route.resume_function(function_key)
    assert resumed == {"key": function_key, "paused": False}
    raw_after_resume = await fake_redis.get(redis_key)
    assert raw_after_resume is not None
    assert json.loads(raw_after_resume.decode())["paused"] is False

    with pytest.raises(HTTPException, match="not found") as missing_exc:
        await functions_route.pause_function("fn.missing")
    assert missing_exc.value.status_code == 404

    await fake_redis.set(
        f"{FUNCTION_KEY_PREFIX}:fn.invalid",
        json.dumps({"name": "bad-shape"}),
    )
    with pytest.raises(
        HTTPException, match="Invalid function definition"
    ) as invalid_exc:
        await functions_route.pause_function("fn.invalid")
    assert invalid_exc.value.status_code == 409


@pytest.mark.asyncio
async def test_workers_route_includes_defs_and_instance_only_workers(
    monkeypatch,
) -> None:
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

    monkeypatch.setattr(workers_root_route, "get_worker_definitions", fake_defs)
    monkeypatch.setattr(workers_root_route, "list_worker_instances", fake_instances)

    out = await workers_route.list_workers_route()
    names = {w.name for w in out.workers}
    assert names == {"defined-worker", "ephemeral-worker"}


@pytest.mark.asyncio
async def test_workers_stream_emits_initial_and_update_frames(monkeypatch) -> None:
    class _RedisStub:
        async def xread(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return [
                (
                    "upnext:workers:events",
                    [
                        (
                            "1000-0",
                            {
                                "data": json.dumps(
                                    {
                                        "type": "worker.heartbeat",
                                        "at": "2026-02-09T12:00:01Z",
                                        "worker_id": "w-1",
                                        "worker_name": "defined-worker",
                                    }
                                )
                            },
                        )
                    ],
                )
            ]

    class _RequestStub:
        def __init__(self) -> None:
            self._calls = 0

        async def is_disconnected(self) -> bool:
            self._calls += 1
            return self._calls > 2

    async def _get_redis() -> _RedisStub:
        return _RedisStub()

    call_count = {"value": 0}

    async def _list_workers() -> workers_route.WorkersListResponse:
        call_count["value"] += 1
        return workers_route.WorkersListResponse(
            workers=[
                workers_route.WorkerInfo(
                    name="defined-worker",
                    active=True,
                    instance_count=1,
                    instances=[],
                    functions=["fn.defined"],
                    function_names={"fn.defined": "defined"},
                    concurrency=2,
                )
            ],
            total=1,
        )

    monkeypatch.setattr(workers_stream_route, "get_redis", _get_redis)
    monkeypatch.setattr(workers_stream_route, "list_workers_route", _list_workers)

    response = await workers_route.stream_workers(_RequestStub())
    body = cast(AsyncIterator[str], response.body_iterator.__aiter__())
    open_frame = await anext(body)
    first_snapshot_frame = await anext(body)
    second_snapshot_frame = await anext(body)

    assert open_frame == "event: open\ndata: connected\n\n"

    first = json.loads(first_snapshot_frame.removeprefix("data: ").strip())
    second = json.loads(second_snapshot_frame.removeprefix("data: ").strip())
    assert first["type"] == "workers.snapshot"
    assert first["workers"]["total"] == 1
    assert second["type"] == "workers.snapshot"
    assert second["workers"]["workers"][0]["name"] == "defined-worker"
    assert call_count["value"] == 2


@pytest.mark.asyncio
async def test_workers_stream_returns_503_when_redis_unavailable(monkeypatch) -> None:
    class _RequestStub:
        async def is_disconnected(self) -> bool:
            return False

    async def _get_redis() -> None:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(workers_stream_route, "get_redis", _get_redis)

    with pytest.raises(HTTPException, match="redis unavailable") as exc:
        await workers_route.stream_workers(_RequestStub())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_dashboard_returns_503_when_database_unavailable(
    monkeypatch,
) -> None:
    import server.routes.depends as depends_module
    from server.routes.depends import require_database

    def _no_db():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(depends_module, "get_database", _no_db)

    with pytest.raises(HTTPException) as exc:
        require_database()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_dashboard_includes_queue_depth_when_database_available(
    sqlite_db, monkeypatch
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "job-queued-1",
                "function": "fn.queue",
                "function_name": "queue",
                "status": "queued",
                "root_id": "job-queued-1",
                "created_at": now,
            }
        )
        await repo.record_job(
            {
                "job_id": "job-complete-1",
                "function": "fn.queue",
                "function_name": "queue",
                "status": "complete",
                "root_id": "job-complete-1",
                "created_at": now,
            }
        )

    class _QueueDepth:
        running = 4
        waiting = 1
        claimed = 5
        scheduled_due = 2
        scheduled_future = 1
        backlog = 8
        capacity = 8
        total = 13

    async def fake_queue_depth() -> _QueueDepth:
        return _QueueDepth()

    async def fake_worker_stats() -> WorkerStats:
        return WorkerStats(total=1)

    class FakeReader:
        async def get_summary_window(
            self, *, minutes: int
        ) -> api_tracking_module.ApiMetricsSummary:
            _ = minutes
            return api_tracking_module.ApiMetricsSummary(
                requests_24h=0,
                avg_latency_ms=0.0,
                error_rate=0.0,
            )

    async def fake_reader() -> FakeReader:
        return FakeReader()

    monkeypatch.setattr(dashboard_route, "get_queue_depth_stats", fake_queue_depth)
    monkeypatch.setattr(dashboard_route, "get_worker_stats", fake_worker_stats)
    monkeypatch.setattr(dashboard_route, "get_metrics_reader", fake_reader)

    out = await dashboard_route.get_dashboard_stats(db=sqlite_db)
    assert out.queue.running == 4
    assert out.queue.waiting == 1
    assert out.queue.claimed == 5
    assert out.queue.scheduled_due == 2
    assert out.queue.scheduled_future == 1
    assert out.queue.backlog == 8
    assert out.queue.capacity == 8
    assert out.queue.total == 13


@pytest.mark.asyncio
async def test_dashboard_window_stats_use_requested_minutes(
    sqlite_db, monkeypatch
) -> None:
    class _QueueDepth:
        running = 1
        waiting = 0
        claimed = 1
        scheduled_due = 0
        scheduled_future = 0
        backlog = 1
        capacity = 10
        total = 2

    async def fake_queue_depth() -> _QueueDepth:
        return _QueueDepth()

    async def fake_worker_stats() -> WorkerStats:
        return WorkerStats(total=1)

    class FakeReader:
        async def get_summary_window(
            self, *, minutes: int
        ) -> api_tracking_module.ApiMetricsSummary:
            if minutes == 5:
                return api_tracking_module.ApiMetricsSummary(
                    requests_24h=25,
                    avg_latency_ms=20.0,
                    error_rate=0.5,
                )
            return api_tracking_module.ApiMetricsSummary(
                requests_24h=1440,
                avg_latency_ms=30.0,
                error_rate=1.5,
            )

    async def fake_reader() -> FakeReader:
        return FakeReader()

    monkeypatch.setattr(dashboard_route, "get_queue_depth_stats", fake_queue_depth)
    monkeypatch.setattr(dashboard_route, "get_worker_stats", fake_worker_stats)
    monkeypatch.setattr(dashboard_route, "get_metrics_reader", fake_reader)

    out = await dashboard_route.get_dashboard_stats(window_minutes=5, db=sqlite_db)
    assert out.runs.window_minutes == 5
    assert out.runs.total == 0
    assert out.runs.jobs_per_min == 0.0
    assert out.apis.window_minutes == 5
    assert out.apis.requests == 25
    assert out.apis.requests_per_min == 5.0
    assert out.apis.avg_latency_ms == 20.0
    assert out.apis.error_rate == 0.5


@pytest.mark.asyncio
async def test_dashboard_includes_runbook_sections(sqlite_db, monkeypatch) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "job-fail-1",
                "function": "fn.fail",
                "function_name": "Fail Fn",
                "status": "failed",
                "root_id": "job-fail-1",
                "created_at": now - timedelta(hours=2),
                "started_at": now - timedelta(hours=2),
                "completed_at": now - timedelta(hours=2) + timedelta(seconds=2),
            }
        )
        await repo.record_job(
            {
                "job_id": "job-fail-2",
                "function": "fn.fail",
                "function_name": "Fail Fn",
                "status": "failed",
                "root_id": "job-fail-2",
                "created_at": now - timedelta(hours=1),
                "started_at": now - timedelta(hours=1),
                "completed_at": now - timedelta(hours=1) + timedelta(seconds=1),
            }
        )
        await repo.record_job(
            {
                "job_id": "job-ok-1",
                "function": "fn.fail",
                "function_name": "Fail Fn",
                "status": "complete",
                "root_id": "job-ok-1",
                "created_at": now - timedelta(minutes=30),
                "started_at": now - timedelta(minutes=30),
                "completed_at": now - timedelta(minutes=30) + timedelta(seconds=1),
            }
        )
        await repo.record_job(
            {
                "job_id": "job-stuck-1",
                "function": "fn.stuck",
                "function_name": "Stuck Fn",
                "status": "active",
                "root_id": "job-stuck-1",
                "worker_id": "worker-a",
                "created_at": now - timedelta(hours=1),
                "started_at": now - timedelta(minutes=40),
            }
        )

    class _QueueDepth:
        running = 1
        waiting = 2
        claimed = 0
        scheduled_due = 1
        scheduled_future = 4
        backlog = 3
        capacity = 4
        total = 8

    class _Settings:
        dashboard_top_failing_limit = 5
        dashboard_oldest_queued_limit = 5
        dashboard_stuck_active_limit = 5
        dashboard_stuck_active_seconds = 900

    async def fake_queue_depth() -> _QueueDepth:
        return _QueueDepth()

    async def fake_worker_stats() -> WorkerStats:
        return WorkerStats(total=2)

    class FakeReader:
        async def get_summary_window(
            self, *, minutes: int
        ) -> api_tracking_module.ApiMetricsSummary:
            _ = minutes
            return api_tracking_module.ApiMetricsSummary(
                requests_24h=0,
                avg_latency_ms=0.0,
                error_rate=0.0,
            )

    async def fake_reader() -> FakeReader:
        return FakeReader()

    async def fake_defs() -> dict[str, FunctionConfig]:
        return {
            "fn.fail": FunctionConfig(
                key="fn.fail",
                name="Orders Processor",
                type=FunctionType.TASK,
            ),
            "fn.stuck": FunctionConfig(
                key="fn.stuck",
                name="Stuck Fn",
                type=FunctionType.TASK,
            ),
        }

    async def fake_oldest(limit: int = 10) -> list[QueuedJobSnapshot]:
        _ = limit
        return [
            QueuedJobSnapshot(
                id="job-q-1",
                function="fn.queue",
                function_name="Queue Fn",
                queued_at=now - timedelta(minutes=12),
                age_seconds=720.0,
                source="stream",
            )
        ]

    monkeypatch.setattr(dashboard_route, "get_settings", lambda: _Settings())
    monkeypatch.setattr(dashboard_route, "get_queue_depth_stats", fake_queue_depth)
    monkeypatch.setattr(dashboard_route, "get_worker_stats", fake_worker_stats)
    monkeypatch.setattr(dashboard_route, "get_metrics_reader", fake_reader)
    monkeypatch.setattr(dashboard_route, "get_function_definitions", fake_defs)
    monkeypatch.setattr(dashboard_route, "get_oldest_queued_jobs", fake_oldest)

    out = await dashboard_route.get_dashboard_stats(db=sqlite_db)
    assert out.top_failing_functions[0].key == "fn.fail"
    assert out.top_failing_functions[0].name == "Orders Processor"
    assert out.top_failing_functions[0].failures == 2
    assert out.top_failing_functions[0].runs == 3
    assert out.top_failing_functions[0].failure_rate == pytest.approx(66.67)
    assert out.stuck_active_jobs[0].id == "job-stuck-1"
    assert out.stuck_active_jobs[0].worker_id == "worker-a"
    assert out.oldest_queued_jobs[0].id == "job-q-1"
    assert out.oldest_queued_jobs[0].source == "stream"

    filtered = await dashboard_route.get_dashboard_stats(failing_min_rate=70.0, db=sqlite_db)
    assert filtered.top_failing_functions == []


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

    monkeypatch.setattr(
        artifacts_root_route.ArtifactRepository, "create", raise_integrity
    )

    response = Response()
    out = await artifacts_root_route.create_artifact(
        "job-art-race",
        CreateArtifactRequest(name="summary", type=ArtifactType.JSON, data={"x": 1}),
        response,
        db=sqlite_db,
    )

    assert response.status_code == 202
    assert out.job_id == "job-art-race"


@pytest.mark.asyncio
async def test_job_artifact_stream_filters_to_requested_job(monkeypatch) -> None:
    class _RedisStub:
        async def xread(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return [
                (
                    ARTIFACT_EVENTS_STREAM,
                    [
                        (
                            "1000-0",
                            {
                                "data": json.dumps(
                                    {
                                        "type": "artifact.created",
                                        "at": "2026-02-09T12:00:00Z",
                                        "job_id": "job-a",
                                        "artifact_id": "artifact-1",
                                        "pending_id": None,
                                        "artifact": {
                                            "id": "artifact-1",
                                            "job_id": "job-a",
                                            "name": "summary",
                                            "type": "json",
                                            "content_type": "application/json",
                                            "size_bytes": 11,
                                            "sha256": "abc123",
                                            "storage_backend": "local",
                                            "storage_key": "jobs/job-a/summary",
                                            "status": "available",
                                            "error": None,
                                            "created_at": "2026-02-09T12:00:00Z",
                                        },
                                    }
                                )
                            },
                        ),
                        (
                            "1001-0",
                            {
                                "data": json.dumps(
                                    {
                                        "type": "artifact.created",
                                        "at": "2026-02-09T12:00:01Z",
                                        "job_id": "job-b",
                                        "artifact_id": "artifact-2",
                                        "pending_id": None,
                                        "artifact": {
                                            "id": "artifact-2",
                                            "job_id": "job-b",
                                            "name": "skip-me",
                                            "type": "json",
                                            "content_type": "application/json",
                                            "size_bytes": 10,
                                            "sha256": "def456",
                                            "storage_backend": "local",
                                            "storage_key": "jobs/job-b/skip-me",
                                            "status": "available",
                                            "error": None,
                                            "created_at": "2026-02-09T12:00:01Z",
                                        },
                                    }
                                )
                            },
                        ),
                    ],
                )
            ]

    class _RequestStub:
        def __init__(self) -> None:
            self._calls = 0

        async def is_disconnected(self) -> bool:
            self._calls += 1
            return self._calls > 2

    async def _get_redis() -> _RedisStub:
        return _RedisStub()

    monkeypatch.setattr(artifacts_stream_route, "get_redis", _get_redis)

    response = await artifacts_stream_route.stream_job_artifacts(
        "job-a", _RequestStub()
    )
    body = cast(AsyncIterator[str], response.body_iterator.__aiter__())
    open_frame = await anext(body)
    event_frame = await anext(body)

    assert open_frame == "event: open\ndata: connected\n\n"
    payload = json.loads(event_frame.removeprefix("data: ").strip())
    assert payload["type"] == "artifact.created"
    assert payload["job_id"] == "job-a"
    assert payload["artifact_id"] == "artifact-1"


@pytest.mark.asyncio
async def test_apis_route_merges_tracked_and_active_instances(monkeypatch) -> None:
    class FakeMetricsReader:
        async def get_apis(self) -> list[api_tracking_module.ApiMetricsByName]:
            return [
                api_tracking_module.ApiMetricsByName(
                    name="tracked-api",
                    endpoint_count=1,
                    requests_24h=10,
                    avg_latency_ms=20.0,
                    error_rate=0.0,
                    requests_per_min=0.5,
                )
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

    monkeypatch.setattr(apis_root_route, "get_metrics_reader", fake_reader)
    monkeypatch.setattr(apis_root_route, "list_api_instances", fake_instances)

    out = await apis_route.list_apis()
    names = {api.name for api in out.apis}
    assert names == {"tracked-api", "instance-only-api"}
    tracked = next(api for api in out.apis if api.name == "tracked-api")
    assert tracked.active is True
    assert tracked.instance_count == 1
