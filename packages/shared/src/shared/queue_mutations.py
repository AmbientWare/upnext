"""Shared queue mutation helpers used by worker and server paths."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.domain.jobs import Job


def prepare_job_for_manual_retry(job: Job) -> None:
    """Reset terminal fields before re-queueing an operator retry."""
    job.mark_queued("Manual retry requested")
    job.scheduled_at = datetime.now(UTC)
    job.started_at = None
    job.completed_at = None
    job.worker_id = None
    job.error = None
    job.error_traceback = None
    job.result = None
    job.progress = 0.0


async def delete_stream_entries_for_job(
    redis_client: Any,
    stream_key: str,
    job_id: str,
    *,
    batch_size: int = 500,
    max_scan: int = 50_000,
) -> int:
    """Delete queued stream entries for a job ID (best effort)."""
    start = "-"
    scanned = 0
    deleted = 0

    while scanned < max_scan:
        rows = await redis_client.xrange(
            stream_key,
            min=start,
            max="+",
            count=batch_size,
        )
        if not rows:
            break

        delete_ids: list[str] = []
        for msg_id, msg_data in rows:
            scanned += 1
            raw_job_id = msg_data.get(b"job_id") or msg_data.get("job_id")
            msg_job_id = (
                raw_job_id.decode() if isinstance(raw_job_id, bytes) else raw_job_id
            )
            if msg_job_id == job_id:
                delete_ids.append(
                    msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                )

        if delete_ids:
            deleted += await redis_client.xdel(stream_key, *delete_ids)

        if len(rows) < batch_size:
            break
        last_id = rows[-1][0]
        last_id_text = last_id.decode() if isinstance(last_id, bytes) else str(last_id)
        start = f"({last_id_text}"

    return deleted
