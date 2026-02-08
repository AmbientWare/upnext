from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from server.db.repository import JobRepository


def _dt(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 2, 8, hour, minute, second, tzinfo=UTC)


@pytest.mark.asyncio
async def test_list_job_subtree_returns_root_and_descendants_only(sqlite_db) -> None:
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "root",
                "function": "fn.root",
                "function_name": "root",
                "status": "complete",
                "root_id": "root",
                "started_at": _dt(10, 0, 0),
                "completed_at": _dt(10, 0, 5),
                "created_at": _dt(10, 0, 0),
            }
        )
        await repo.record_job(
            {
                "job_id": "child",
                "function": "fn.child",
                "function_name": "child",
                "status": "complete",
                "parent_id": "root",
                "root_id": "root",
                "started_at": _dt(10, 0, 1),
                "completed_at": _dt(10, 0, 4),
                "created_at": _dt(10, 0, 1),
            }
        )
        await repo.record_job(
            {
                "job_id": "grandchild",
                "function": "fn.grand",
                "function_name": "grand",
                "status": "complete",
                "parent_id": "child",
                "root_id": "root",
                "started_at": _dt(10, 0, 2),
                "completed_at": _dt(10, 0, 3),
                "created_at": _dt(10, 0, 2),
            }
        )
        await repo.record_job(
            {
                "job_id": "other-root",
                "function": "fn.other",
                "function_name": "other",
                "status": "complete",
                "root_id": "other-root",
                "started_at": _dt(9, 0, 0),
                "completed_at": _dt(9, 0, 1),
                "created_at": _dt(9, 0, 0),
            }
        )

    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        jobs = await repo.list_job_subtree("root")

    assert [job.id for job in jobs] == ["root", "child", "grandchild"]


@pytest.mark.asyncio
async def test_get_durations_uses_sql_duration_expression(sqlite_db) -> None:
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "dur-1",
                "function": "fn.duration",
                "function_name": "duration",
                "status": "complete",
                "root_id": "dur-1",
                "started_at": _dt(11, 0, 0),
                "completed_at": _dt(11, 0, 1),
                "created_at": _dt(11, 0, 0),
            }
        )
        await repo.record_job(
            {
                "job_id": "dur-2",
                "function": "fn.duration",
                "function_name": "duration",
                "status": "complete",
                "root_id": "dur-2",
                "started_at": _dt(11, 0, 0),
                "completed_at": _dt(11, 0, 3),
                "created_at": _dt(11, 0, 0),
            }
        )

    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        values = await repo.get_durations(
            function="fn.duration",
            start_date=_dt(10),
        )

    assert len(values) == 2
    assert round(values[0]) == 1000
    assert round(values[1]) == 3000


@pytest.mark.asyncio
async def test_list_jobs_filters_and_pagination(sqlite_db) -> None:
    base = datetime(2026, 2, 8, 12, 0, tzinfo=UTC)
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        for idx in range(6):
            await repo.record_job(
                {
                    "job_id": f"job-{idx}",
                    "function": "fn.target" if idx < 5 else "fn.other",
                    "function_name": "target" if idx < 5 else "other",
                    "status": "failed" if idx % 2 else "complete",
                    "worker_id": "worker-a" if idx < 4 else "worker-b",
                    "root_id": f"job-{idx}",
                    "created_at": base + timedelta(minutes=idx),
                    "started_at": base + timedelta(minutes=idx),
                    "completed_at": base + timedelta(minutes=idx, seconds=1),
                }
            )

    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        rows = await repo.list_jobs(
            function="fn.target",
            status=["failed"],
            worker_id="worker-a",
            limit=1,
            offset=0,
        )
        total = await repo.count_jobs(
            function="fn.target",
            status=["failed"],
            worker_id="worker-a",
        )

    assert total == 2
    assert len(rows) == 1
    assert rows[0].function == "fn.target"
    assert rows[0].status == "failed"
    assert rows[0].worker_id == "worker-a"


@pytest.mark.asyncio
async def test_hourly_trends_zero_fill_consumer_behavior(sqlite_db) -> None:
    # Insert two jobs in distinct hours and assert grouped rows are returned in hour order.
    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        await repo.record_job(
            {
                "job_id": "trend-1",
                "function": "fn.t",
                "function_name": "trend",
                "status": "complete",
                "root_id": "trend-1",
                "created_at": _dt(8, 5),
            }
        )
        await repo.record_job(
            {
                "job_id": "trend-2",
                "function": "fn.t",
                "function_name": "trend",
                "status": "failed",
                "root_id": "trend-2",
                "created_at": _dt(9, 10),
            }
        )

    async with sqlite_db.session() as session:
        repo = JobRepository(session)
        rows = await repo.get_hourly_trends(
            start_date=_dt(8, 0),
            end_date=_dt(10, 0),
            function="fn.t",
        )

    hours = [(int(r.yr), int(r.mo), int(r.dy), int(r.hr)) for r in rows]
    assert hours == sorted(hours)
    statuses = {r.status for r in rows}
    assert statuses == {"complete", "failed"}
