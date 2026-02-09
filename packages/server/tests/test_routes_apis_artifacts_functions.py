from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import AsyncIterator, cast

import pytest
from fastapi import HTTPException, Response
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from shared.schemas import (
    ApiInstance,
    ApiPageResponse,
    ApisListResponse,
    ArtifactQueuedResponse,
    ArtifactResponse,
    ArtifactType,
    CreateArtifactRequest,
    FunctionType,
    WorkerInstance,
)

from server.db.models import PendingArtifact
from server.db.repository import JobRepository
import server.routes.apis as apis_route
import server.routes.apis.apis_root as apis_root_route
import server.routes.apis.apis_stream as apis_stream_route
import server.routes.apis.apis_utils as apis_utils_route
import server.routes.artifacts as artifacts_route
import server.routes.artifacts.job_artifacts as job_artifacts_route
import server.routes.artifacts.artifacts_root as artifacts_root_route
import server.routes.functions as functions_route
from server.routes import v1_router


def _worker(
    *,
    worker_id: str,
    worker_name: str,
    functions: list[str],
    hostname: str | None = None,
) -> WorkerInstance:
    now = datetime.now(UTC).isoformat()
    return WorkerInstance(
        id=worker_id,
        worker_name=worker_name,
        started_at=now,
        last_heartbeat=now,
        functions=functions,
        function_names={key: key for key in functions},
        concurrency=1,
        active_jobs=0,
        jobs_processed=0,
        jobs_failed=0,
        hostname=hostname,
    )


def test_calculate_artifact_size_handles_supported_payload_types() -> None:
    assert artifacts_route.calculate_artifact_size(None) is None
    assert artifacts_route.calculate_artifact_size("hello") == 5
    assert artifacts_route.calculate_artifact_size({"x": 1}) == len(
        json.dumps({"x": 1}).encode("utf-8")
    )
    assert artifacts_route.calculate_artifact_size([1, 2]) == len(
        json.dumps([1, 2]).encode("utf-8")
    )
    assert artifacts_route.calculate_artifact_size(123) is None


@pytest.mark.asyncio
async def test_artifact_routes_create_list_get_delete_round_trip(
    sqlite_db, monkeypatch
) -> None:
    now = datetime.now(UTC)
    async with sqlite_db.session() as session:
        jobs = JobRepository(session)
        await jobs.record_job(
            {
                "job_id": "artifact-job-1",
                "function": "fn.artifact",
                "function_name": "artifact",
                "status": "active",
                "root_id": "artifact-job-1",
                "created_at": now,
            }
        )

    monkeypatch.setattr(job_artifacts_route, "get_database", lambda: sqlite_db)
    monkeypatch.setattr(artifacts_root_route, "get_database", lambda: sqlite_db)

    create_response = Response()
    created = await artifacts_route.create_artifact(
        "artifact-job-1",
        CreateArtifactRequest(name="summary", type=ArtifactType.TEXT, data="hello"),
        create_response,
    )
    assert isinstance(created, ArtifactResponse)
    assert create_response.status_code == 200
    assert created.job_id == "artifact-job-1"
    assert created.name == "summary"
    assert created.type == ArtifactType.TEXT
    assert created.size_bytes == 5

    listed = await artifacts_route.list_artifacts("artifact-job-1")
    assert listed.total == 1
    assert listed.artifacts[0].id == created.id
    assert listed.artifacts[0].data == "hello"

    fetched = await artifacts_route.get_artifact(created.id)
    assert fetched.id == created.id
    assert fetched.job_id == "artifact-job-1"

    deleted = await artifacts_route.delete_artifact(created.id)
    assert deleted == {"status": "deleted", "id": created.id}

    with pytest.raises(HTTPException, match="Artifact not found") as get_missing_exc:
        await artifacts_route.get_artifact(created.id)
    assert get_missing_exc.value.status_code == 404

    with pytest.raises(HTTPException, match="Artifact not found") as delete_missing_exc:
        await artifacts_route.delete_artifact(created.id)
    assert delete_missing_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_artifact_queues_pending_when_job_row_missing(
    sqlite_db, monkeypatch
) -> None:
    monkeypatch.setattr(job_artifacts_route, "get_database", lambda: sqlite_db)

    response = Response()
    queued = await artifacts_route.create_artifact(
        "missing-job",
        CreateArtifactRequest(name="payload", type=ArtifactType.JSON, data={"ok": True}),
        response,
    )
    assert isinstance(queued, ArtifactQueuedResponse)
    assert response.status_code == 202
    assert queued.status == "queued"
    assert queued.job_id == "missing-job"

    async with sqlite_db.session() as session:
        rows = (
            await session.execute(
                select(PendingArtifact).where(PendingArtifact.job_id == "missing-job")
            )
        ).scalars().all()

    assert len(rows) == 1
    assert rows[0].name == "payload"
    assert rows[0].size_bytes == len(json.dumps({"ok": True}).encode("utf-8"))

    listed = await artifacts_route.list_artifacts("missing-job")
    assert listed.total == 0
    assert listed.artifacts == []


@pytest.mark.asyncio
async def test_artifact_routes_handle_database_unavailable(monkeypatch) -> None:
    def _no_db():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(job_artifacts_route, "get_database", _no_db)
    monkeypatch.setattr(artifacts_root_route, "get_database", _no_db)

    with pytest.raises(HTTPException, match="Database not available") as create_exc:
        await artifacts_route.create_artifact(
            "job-1",
            CreateArtifactRequest(name="x", type=ArtifactType.TEXT, data="payload"),
            Response(),
        )
    assert create_exc.value.status_code == 503

    listed = await artifacts_route.list_artifacts("job-1")
    assert listed.total == 0
    assert listed.artifacts == []

    with pytest.raises(HTTPException, match="Database not available") as get_exc:
        await artifacts_route.get_artifact(1)
    assert get_exc.value.status_code == 503

    with pytest.raises(HTTPException, match="Database not available") as del_exc:
        await artifacts_route.delete_artifact(1)
    assert del_exc.value.status_code == 503


@pytest.mark.asyncio
async def test_list_functions_handles_runtime_failures(monkeypatch) -> None:
    async def _fail_defs() -> dict:
        raise RuntimeError("definitions unavailable")

    def _no_db():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(functions_route, "get_function_definitions", _fail_defs)
    monkeypatch.setattr(functions_route, "get_database", _no_db)

    out = await functions_route.list_functions(type=None)
    assert out.total == 0
    assert out.functions == []


@pytest.mark.asyncio
async def test_list_functions_merges_stats_filters_and_worker_labels(
    sqlite_db, monkeypatch
) -> None:
    now = datetime.now(UTC)
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "fn-task-1",
                "function": "fn.task",
                "function_name": "task",
                "status": "complete",
                "root_id": "fn-task-1",
                "created_at": now - timedelta(hours=2),
                "started_at": now - timedelta(hours=2),
                "completed_at": now - timedelta(hours=2) + timedelta(seconds=1),
            }
        )
        await repo.record_job(
            {
                "job_id": "fn-task-2",
                "function": "fn.task",
                "function_name": "task",
                "status": "failed",
                "root_id": "fn-task-2",
                "created_at": now - timedelta(hours=1),
                "started_at": now - timedelta(hours=1),
                "completed_at": now - timedelta(hours=1) + timedelta(seconds=3),
            }
        )

    async def _defs() -> dict[str, dict]:
        return {
            "fn.task": {
                "key": "fn.task",
                "name": "Task Fn",
                "type": FunctionType.TASK,
                "timeout": 30,
                "max_retries": 2,
                "retry_delay": 3,
            },
            "fn.event": {
                "key": "fn.event",
                "name": "Event Fn",
                "type": FunctionType.EVENT,
                "pattern": "user.*",
            },
        }

    async def _workers() -> list[WorkerInstance]:
        return [
            _worker(worker_id="worker-a-1", worker_name="alpha", functions=["fn.task"]),
            _worker(worker_id="worker-a-2", worker_name="alpha", functions=["fn.task"]),
            _worker(
                worker_id="worker-host-1",
                worker_name="",
                hostname="host-1",
                functions=["fn.task", "fn.event"],
            ),
            _worker(
                worker_id="workerid00000000",
                worker_name="",
                hostname=None,
                functions=["fn.event"],
            ),
        ]

    monkeypatch.setattr(functions_route, "get_function_definitions", _defs)
    monkeypatch.setattr(functions_route, "list_worker_instances", _workers)
    monkeypatch.setattr(functions_route, "get_database", lambda: sqlite_db)

    all_functions = await functions_route.list_functions(type=None)
    assert all_functions.total == 2

    by_key = {item.key: item for item in all_functions.functions}
    task = by_key["fn.task"]
    event = by_key["fn.event"]

    assert task.runs_24h == 2
    assert task.success_rate == 50.0
    assert set(task.workers) == {"alpha (2)", "host-1"}
    assert task.active is True

    assert event.runs_24h == 0
    assert event.success_rate == 100.0
    assert set(event.workers) == {"host-1", "workerid"}
    assert event.active is True

    event_only = await functions_route.list_functions(type=FunctionType.EVENT)
    assert event_only.total == 1
    assert event_only.functions[0].key == "fn.event"


@pytest.mark.asyncio
async def test_get_function_computes_duration_percentile_and_recent_runs(
    sqlite_db, monkeypatch
) -> None:
    now = datetime.now(UTC)
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "fn-detail-1",
                "function": "fn.detail",
                "function_name": "detail",
                "status": "complete",
                "root_id": "fn-detail-1",
                "created_at": now - timedelta(minutes=5),
                "started_at": now - timedelta(minutes=5),
                "completed_at": now - timedelta(minutes=5) + timedelta(seconds=1),
            }
        )
        await repo.record_job(
            {
                "job_id": "fn-detail-2",
                "function": "fn.detail",
                "function_name": "detail",
                "status": "failed",
                "root_id": "fn-detail-2",
                "created_at": now - timedelta(minutes=4),
                "started_at": now - timedelta(minutes=4),
                "completed_at": now - timedelta(minutes=4) + timedelta(seconds=3),
                "error": "boom",
            }
        )
        await repo.record_job(
            {
                "job_id": "fn-detail-3",
                "function": "fn.detail",
                "function_name": "detail",
                "status": "active",
                "root_id": "fn-detail-3",
                "created_at": now - timedelta(minutes=3),
                "started_at": now - timedelta(minutes=3),
            }
        )

    async def _defs() -> dict[str, dict]:
        return {
            "fn.detail": {
                "key": "fn.detail",
                "name": "Detail Fn",
                "type": FunctionType.CRON,
                "schedule": "0 * * * *",
            }
        }

    async def _workers() -> list[WorkerInstance]:
        return [
            _worker(
                worker_id="worker-1",
                worker_name="worker-a",
                functions=["fn.detail"],
            ),
            _worker(
                worker_id="worker-2",
                worker_name="worker-a",
                functions=["fn.detail"],
            ),
        ]

    monkeypatch.setattr(functions_route, "get_function_definitions", _defs)
    monkeypatch.setattr(functions_route, "list_worker_instances", _workers)
    monkeypatch.setattr(functions_route, "get_database", lambda: sqlite_db)

    detail = await functions_route.get_function("fn.detail")
    assert detail.type == FunctionType.CRON
    assert detail.runs_24h == 3
    assert detail.success_rate == 33.3
    assert detail.avg_duration_ms == pytest.approx(2000.0, abs=0.1)
    assert detail.p95_duration_ms == pytest.approx(3000.0, abs=0.1)
    assert detail.last_run_status == "active"
    assert detail.workers == ["worker-a (2)"]
    assert [run.id for run in detail.recent_runs] == [
        "fn-detail-3",
        "fn-detail-2",
        "fn-detail-1",
    ]
    assert detail.recent_runs[0].duration_ms is None
    assert detail.recent_runs[1].duration_ms == 3000.0


@pytest.mark.asyncio
async def test_get_function_defaults_when_backends_unavailable(monkeypatch) -> None:
    async def _fail_defs() -> dict:
        raise RuntimeError("defs down")

    def _no_db():
        raise RuntimeError("db down")

    monkeypatch.setattr(functions_route, "get_function_definitions", _fail_defs)
    monkeypatch.setattr(functions_route, "get_database", _no_db)

    detail = await functions_route.get_function("fn.missing")
    assert detail.key == "fn.missing"
    assert detail.name == "fn.missing"
    assert detail.type == FunctionType.TASK
    assert detail.active is False
    assert detail.workers == []
    assert detail.runs_24h == 0
    assert detail.success_rate == 100.0
    assert detail.recent_runs == []


@pytest.mark.asyncio
async def test_apis_routes_list_detail_and_trends(monkeypatch) -> None:
    class _Reader:
        async def get_apis(self) -> list[dict]:
            return [
                {
                    "name": "orders",
                    "endpoint_count": 1,
                    "requests_24h": 12,
                    "avg_latency_ms": 21.5,
                    "error_rate": 8.3,
                    "requests_per_min": 0.5,
                }
            ]

        async def get_endpoints(self, api_name: str | None = None) -> list[dict]:
            rows = [
                {
                    "api_name": "orders",
                    "method": "GET",
                    "path": "/orders",
                    "requests_24h": 12,
                    "requests_per_min": 0.5,
                    "avg_latency_ms": 21.5,
                    "p50_latency_ms": 20.0,
                    "p95_latency_ms": 30.0,
                    "p99_latency_ms": 35.0,
                    "error_rate": 8.3,
                    "success_rate": 91.7,
                    "client_error_rate": 8.3,
                    "server_error_rate": 0.0,
                    "status_2xx": 11,
                    "status_4xx": 1,
                    "status_5xx": 0,
                    "last_request_at": datetime.now(UTC).isoformat(),
                }
            ]
            if api_name is None:
                return rows
            return [row for row in rows if row["api_name"] == api_name]

        async def get_hourly_trends(self, hours: int) -> list[dict]:  # noqa: ARG002
            return [
                {
                    "hour": "2026-02-08T10:00:00Z",
                    "success_2xx": 10,
                    "client_4xx": 1,
                    "server_5xx": 1,
                }
            ]

    async def _reader() -> _Reader:
        return _Reader()

    async def _instances() -> list[ApiInstance]:
        now = datetime.now(UTC).isoformat()
        return [
            ApiInstance(
                id="api-1",
                api_name="orders",
                started_at=now,
                last_heartbeat=now,
                host="0.0.0.0",
                port=8080,
                endpoints=["GET:/orders"],
                hostname=None,
            ),
            ApiInstance(
                id="api-2",
                api_name="instance-only",
                started_at=now,
                last_heartbeat=now,
                host="0.0.0.0",
                port=8081,
                endpoints=["GET:/health"],
                hostname=None,
            ),
        ]

    class _Settings:
        api_docs_url_template = "http://{host}:{port}/docs"

    monkeypatch.setattr(apis_utils_route, "get_settings", lambda: _Settings())
    monkeypatch.setattr(apis_root_route, "get_metrics_reader", _reader)
    monkeypatch.setattr(apis_root_route, "list_api_instances", _instances)

    listed = await apis_route.list_apis()
    assert listed.total == 2
    by_name = {api.name: api for api in listed.apis}
    assert by_name["orders"].active is True
    assert by_name["orders"].instance_count == 1
    assert by_name["instance-only"].active is True
    assert by_name["instance-only"].requests_24h == 0

    endpoints = await apis_route.list_endpoints()
    assert endpoints.total == 1
    assert endpoints.endpoints[0].method == "GET"
    assert endpoints.endpoints[0].path == "/orders"

    trends = await apis_route.get_api_trends(hours=12)
    assert len(trends.hourly) == 1
    assert trends.hourly[0].success_2xx == 10

    found = await apis_route.get_endpoint("get", "orders")
    assert found.method == "GET"
    assert found.path == "/orders"

    api_page = await apis_route.get_api("orders")
    assert api_page.api.name == "orders"
    assert api_page.api.docs_url == "http://localhost:8080/docs"
    assert api_page.api.requests_24h == 12
    assert api_page.api.success_rate == 91.7
    assert api_page.total_endpoints == 1
    assert api_page.endpoints[0].path == "/orders"

    missing = await apis_route.get_endpoint("post", "missing")
    assert missing.method == "POST"
    assert missing.path == "/missing"


@pytest.mark.asyncio
async def test_apis_routes_fallback_to_empty_when_sources_fail(monkeypatch) -> None:
    async def _fail_reader():
        raise RuntimeError("metrics unavailable")

    async def _fail_instances():
        raise RuntimeError("instances unavailable")

    monkeypatch.setattr(apis_root_route, "get_metrics_reader", _fail_reader)
    monkeypatch.setattr(apis_root_route, "list_api_instances", _fail_instances)

    listed = await apis_route.list_apis()
    assert listed.total == 0
    assert listed.apis == []

    endpoints = await apis_route.list_endpoints()
    assert endpoints.total == 0
    assert endpoints.endpoints == []

    trends = await apis_route.get_api_trends(hours=24)
    assert trends.hourly == []

    detail = await apis_route.get_endpoint("get", "missing")
    assert detail.method == "GET"
    assert detail.path == "/missing"

    api_page = await apis_route.get_api("missing")
    assert api_page.api.name == "missing"
    assert api_page.api.docs_url is None
    assert api_page.total_endpoints == 0


@pytest.mark.asyncio
async def test_apis_stream_routes_emit_snapshot_frames(monkeypatch) -> None:
    class _Settings:
        api_realtime_enabled = True
        api_request_events_default_limit = 200

    class _RedisStub:
        async def xread(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    async def _list_apis() -> ApisListResponse:
        return ApisListResponse(
            apis=[
                apis_route.ApiInfo(
                    name="orders",
                    active=True,
                    instance_count=1,
                    endpoint_count=2,
                    requests_24h=123,
                    avg_latency_ms=12.5,
                    error_rate=0.8,
                    requests_per_min=2.2,
                )
            ],
            total=1,
        )

    async def _get_api(name: str) -> ApiPageResponse:
        return ApiPageResponse(
            api=apis_route.ApiOverview(name=name, requests_24h=123, endpoint_count=2),
            endpoints=[],
            total_endpoints=0,
        )

    class _RequestStub:
        async def is_disconnected(self) -> bool:
            return False

    async def _get_redis() -> _RedisStub:
        return _RedisStub()

    monkeypatch.setattr(apis_stream_route, "get_settings", lambda: _Settings())
    monkeypatch.setattr(apis_stream_route, "list_apis", _list_apis)
    monkeypatch.setattr(apis_stream_route, "get_api", _get_api)
    monkeypatch.setattr(apis_stream_route, "get_redis", _get_redis)

    list_response = await apis_route.stream_apis(_RequestStub())
    list_stream = cast(AsyncIterator[str], list_response.body_iterator.__aiter__())
    open_frame = await anext(list_stream)
    snapshot_frame = await anext(list_stream)

    detail_response = await apis_route.stream_api("orders", _RequestStub())
    detail_stream = cast(AsyncIterator[str], detail_response.body_iterator.__aiter__())
    detail_open_frame = await anext(detail_stream)
    detail_snapshot_frame = await anext(detail_stream)

    assert open_frame == "event: open\ndata: connected\n\n"
    assert detail_open_frame == "event: open\ndata: connected\n\n"

    list_payload = json.loads(snapshot_frame.removeprefix("data: ").strip())
    detail_payload = json.loads(detail_snapshot_frame.removeprefix("data: ").strip())

    assert list_payload["type"] == "apis.snapshot"
    assert list_payload["apis"]["total"] == 1
    assert detail_payload["type"] == "api.snapshot"
    assert detail_payload["api"]["api"]["name"] == "orders"

    list_closer = getattr(list_response.body_iterator, "aclose", None)
    if callable(list_closer):
        await list_closer()
    detail_closer = getattr(detail_response.body_iterator, "aclose", None)
    if callable(detail_closer):
        await detail_closer()


@pytest.mark.asyncio
async def test_apis_stream_routes_can_be_disabled(monkeypatch) -> None:
    class _Settings:
        api_realtime_enabled = False
        api_request_events_default_limit = 200

    class _RequestStub:
        async def is_disconnected(self) -> bool:
            return False

    monkeypatch.setattr(apis_stream_route, "get_settings", lambda: _Settings())

    with pytest.raises(HTTPException, match="disabled") as list_exc:
        await apis_route.stream_apis(_RequestStub())
    assert list_exc.value.status_code == 404

    with pytest.raises(HTTPException, match="disabled") as detail_exc:
        await apis_route.stream_api("orders", _RequestStub())
    assert detail_exc.value.status_code == 404

    with pytest.raises(HTTPException, match="disabled") as events_exc:
        await apis_route.stream_api_request_events(_RequestStub())
    assert events_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_request_events_list_and_stream_routes(monkeypatch) -> None:
    class _Settings:
        api_realtime_enabled = True
        api_request_events_default_limit = 200

    class _RedisStub:
        async def xrevrange(self, _stream: str, count: int):  # type: ignore[no-untyped-def]
            _ = count
            return [
                (
                    "1000-0",
                    {
                        "data": json.dumps(
                            {
                                "id": "evt-1",
                                "at": "2026-02-09T12:00:00Z",
                                "api_name": "orders",
                                "method": "GET",
                                "path": "/orders/{order_id}",
                                "status": 200,
                                "latency_ms": 12.4,
                                "instance_id": "api_a",
                                "sampled": False,
                            }
                        )
                    },
                )
            ]

        async def xread(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return [
                (
                    "conduit:api:requests",
                    [
                        (
                            "1001-0",
                            {
                                "data": json.dumps(
                                    {
                                        "id": "evt-2",
                                        "at": "2026-02-09T12:00:01Z",
                                        "api_name": "orders",
                                        "method": "POST",
                                        "path": "/orders",
                                        "status": 201,
                                        "latency_ms": 18.0,
                                        "instance_id": "api_a",
                                        "sampled": True,
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

    monkeypatch.setattr(apis_stream_route, "get_settings", lambda: _Settings())
    monkeypatch.setattr(apis_stream_route, "get_redis", _get_redis)

    listed = await apis_route.list_api_request_events(api_name="orders", limit=10)
    assert listed.total == 1
    assert listed.events[0].id == "evt-1"
    assert listed.events[0].path == "/orders/{order_id}"

    response = await apis_route.stream_api_request_events(
        _RequestStub(), api_name="orders"
    )
    body = cast(AsyncIterator[str], response.body_iterator.__aiter__())
    open_frame = await anext(body)
    event_frame = await anext(body)

    assert open_frame == "event: open\ndata: connected\n\n"
    payload = json.loads(event_frame.removeprefix("data: ").strip())
    assert payload["type"] == "api.request"
    assert payload["request"]["id"] == "evt-2"
    assert payload["request"]["api_name"] == "orders"


@pytest.mark.asyncio
async def test_api_request_events_skip_malformed_rows_without_crashing(
    monkeypatch,
) -> None:
    class _Settings:
        api_realtime_enabled = True
        api_request_events_default_limit = 200

    class _RedisStub:
        async def xrevrange(self, _stream: str, count: int):  # type: ignore[no-untyped-def]
            _ = count
            return [
                (
                    "2000-0",
                    {
                        "at": "2026-02-09T12:00:00Z",
                        "api_name": "orders",
                        "method": "GET",
                        "path": "/orders",
                        "status": "not-a-number",
                        "latency_ms": "12.4",
                    },
                ),
                (
                    "1999-0",
                    {
                        "data": json.dumps(
                            {
                                "id": "evt-valid",
                                "at": "2026-02-09T12:00:01Z",
                                "api_name": "orders",
                                "method": "POST",
                                "path": "/orders",
                                "status": 201,
                                "latency_ms": 18.0,
                                "instance_id": "api_a",
                                "sampled": True,
                            }
                        )
                    },
                ),
            ]

    async def _get_redis() -> _RedisStub:
        return _RedisStub()

    monkeypatch.setattr(apis_stream_route, "get_settings", lambda: _Settings())
    monkeypatch.setattr(apis_stream_route, "get_redis", _get_redis)

    listed = await apis_route.list_api_request_events(api_name="orders", limit=10)
    assert listed.total == 1
    assert listed.events[0].id == "evt-valid"


@pytest.mark.asyncio
async def test_apis_events_stream_path_not_captured_by_endpoint_detail(
    monkeypatch,
) -> None:
    class _Settings:
        api_realtime_enabled = False

    monkeypatch.setattr(apis_stream_route, "get_settings", lambda: _Settings())

    app = FastAPI()
    app.include_router(v1_router)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/apis/events/stream")

    assert response.status_code == 404
    assert "disabled" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_trends_stream_emits_initial_and_update_frames(monkeypatch) -> None:
    class _Settings:
        api_realtime_enabled = True
        api_request_events_default_limit = 200

    class _RedisStub:
        async def xread(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return [
                (
                    "conduit:api:requests",
                    [
                        (
                            "1001-0",
                            {
                                "data": json.dumps(
                                    {
                                        "id": "evt-2",
                                        "at": "2026-02-09T12:00:01Z",
                                        "api_name": "orders",
                                        "method": "POST",
                                        "path": "/orders",
                                        "status": 201,
                                        "latency_ms": 18.0,
                                        "instance_id": "api_a",
                                        "sampled": True,
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

    async def _get_api_trends(hours: int = 24) -> apis_route.ApiTrendsResponse:
        _ = hours
        call_count["value"] += 1
        return apis_route.ApiTrendsResponse(
            hourly=[
                apis_route.ApiTrendHour(
                    hour="2026-02-09T12:00:00Z",
                    success_2xx=call_count["value"],
                    client_4xx=0,
                    server_5xx=0,
                )
            ]
        )

    monkeypatch.setattr(apis_stream_route, "get_settings", lambda: _Settings())
    monkeypatch.setattr(apis_stream_route, "get_redis", _get_redis)
    monkeypatch.setattr(apis_stream_route, "get_api_trends", _get_api_trends)

    response = await apis_route.stream_api_trends(_RequestStub())
    body = cast(AsyncIterator[str], response.body_iterator.__aiter__())
    open_frame = await anext(body)
    first_snapshot_frame = await anext(body)
    second_snapshot_frame = await anext(body)

    assert open_frame == "event: open\ndata: connected\n\n"
    first = json.loads(first_snapshot_frame.removeprefix("data: ").strip())
    second = json.loads(second_snapshot_frame.removeprefix("data: ").strip())
    assert first["type"] == "apis.trends.snapshot"
    assert first["trends"]["hourly"][0]["success_2xx"] == 1
    assert second["type"] == "apis.trends.snapshot"
    assert second["trends"]["hourly"][0]["success_2xx"] == 2
