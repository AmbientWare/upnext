from __future__ import annotations

import pytest
from shared.domain.jobs import Job, JobStatus
from shared.keys import (
    function_dedup_key,
    function_stream_key,
    job_cancelled_key,
    job_index_key,
    job_key,
)

from server.services.jobs.queue_mutations import cancel_job, manual_retry


@pytest.mark.asyncio
async def test_cancel_job_does_not_override_existing_terminal_payload(fake_redis) -> None:
    active = Job(id="job-race-cancel-1", function="fn.cancel", function_name="cancel")
    active.mark_queued("queued")
    active_key = job_key(active.function, active.id)
    await fake_redis.setex(active_key, 86_400, active.to_json())
    await fake_redis.setex(job_index_key(active.id), 86_400, active_key)

    terminal = Job(
        id=active.id,
        function=active.function,
        function_name=active.function_name,
        status=JobStatus.COMPLETE,
    )
    terminal.mark_complete({"ok": True})
    await fake_redis.setex(active_key, 86_400, terminal.to_json())

    active.mark_cancelled()
    result = await cancel_job(fake_redis, active, existing_job_key=active_key)

    assert result.cancelled is False
    assert result.deleted_stream_entries == 0
    assert await fake_redis.get(job_cancelled_key(active.id)) is None

    stored_job = await fake_redis.get(active_key)
    assert stored_job is not None
    loaded = Job.from_json(stored_job.decode())
    assert loaded.status == JobStatus.COMPLETE


@pytest.mark.asyncio
async def test_cancel_job_preserves_existing_cancel_marker_on_race(fake_redis) -> None:
    active = Job(
        id="job-race-cancel-marker-1",
        function="fn.cancel",
        function_name="cancel",
    )
    active.mark_queued("queued")
    active_key = job_key(active.function, active.id)
    await fake_redis.setex(active_key, 86_400, active.to_json())
    await fake_redis.setex(job_index_key(active.id), 86_400, active_key)
    await fake_redis.setex(job_cancelled_key(active.id), 86_400, "1")

    terminal = Job(
        id=active.id,
        function=active.function,
        function_name=active.function_name,
        status=JobStatus.COMPLETE,
    )
    terminal.mark_complete({"ok": True})
    await fake_redis.setex(active_key, 86_400, terminal.to_json())

    active.mark_cancelled()
    result = await cancel_job(fake_redis, active, existing_job_key=active_key)

    assert result.cancelled is False
    assert await fake_redis.get(job_cancelled_key(active.id)) == b"1"


@pytest.mark.asyncio
async def test_manual_retry_preserves_attempt_counter(fake_redis) -> None:
    failed = Job(id="job-retry-attempts-1", function="fn.retry", function_name="retry")
    failed.attempts = 3
    failed.mark_failed("boom")
    failed.key = "retry-attempts-key"
    failed_key = job_key(failed.function, failed.id)
    await fake_redis.setex(failed_key, 86_400, failed.to_json())
    await fake_redis.setex(job_index_key(failed.id), 86_400, failed_key)

    await manual_retry(fake_redis, failed)

    stored = await fake_redis.get(job_key(failed.function, failed.id))
    assert stored is not None
    requeued = Job.from_json(stored.decode())
    assert requeued.status == JobStatus.QUEUED
    assert requeued.attempts == 3
    assert requeued.error is None
    assert requeued.result is None
    assert await fake_redis.sismember(
        function_dedup_key(failed.function), failed.key
    ) == 1


@pytest.mark.asyncio
async def test_cancel_job_successfully_deletes_queued_payload(fake_redis) -> None:
    queued = Job(id="job-cancel-success-1", function="fn.cancel", function_name="cancel")
    queued.mark_queued("queued")
    queued.key = "cancel-success-key"

    queued_key = job_key(queued.function, queued.id)
    await fake_redis.setex(queued_key, 86_400, queued.to_json())
    await fake_redis.setex(job_index_key(queued.id), 86_400, queued_key)
    await fake_redis.sadd(function_dedup_key(queued.function), queued.key)
    await fake_redis.xadd(
        function_stream_key(queued.function),
        {"job_id": queued.id, "function": queued.function, "data": queued.to_json()},
    )

    queued.mark_cancelled()
    result = await cancel_job(fake_redis, queued, existing_job_key=queued_key)
    assert result.cancelled is True

    assert await fake_redis.get(queued_key) is None
    assert await fake_redis.sismember(function_dedup_key(queued.function), queued.key) == 0
