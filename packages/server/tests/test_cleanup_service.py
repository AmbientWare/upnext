from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from server.db.repositories import ArtifactRepository, JobRepository
from server.db.tables import Artifact, JobHistory, PendingArtifact
from server.services.operations.cleanup import CleanupService
from sqlalchemy import select


@pytest.mark.asyncio
async def test_cleanup_service_promotes_pending_and_deletes_old_rows(sqlite_db) -> None:
    now = datetime.now(UTC)

    async with sqlite_db.session() as session:
        job_repo = JobRepository(session)
        artifact_repo = ArtifactRepository(session)

        # Old job should be deleted by retention policy.
        await job_repo.record_job(
            {
                "job_id": "old-job",
                "function": "fn.old",
                "function_name": "old",
                "status": "complete",
                "root_id": "old-job",
                "created_at": now - timedelta(days=40),
            }
        )

        # Fresh job should remain and receive pending artifact promotion.
        await job_repo.record_job(
            {
                "job_id": "fresh-job",
                "function": "fn.fresh",
                "function_name": "fresh",
                "status": "active",
                "root_id": "fresh-job",
                "created_at": now,
            }
        )
        await artifact_repo.create_pending(
            job_id="fresh-job",
            name="artifact",
            artifact_type="json",
            data={"x": 1},
        )

    service = CleanupService(
        redis_client=None,
        retention_days=30,
        interval_hours=1,
        pending_retention_hours=24,
        pending_promote_batch=100,
        pending_promote_max_loops=2,
        startup_jitter_seconds=0,
    )
    await service._run_cleanup()  # noqa: SLF001

    async with sqlite_db.session() as session:
        old = await session.get(JobHistory, "old-job")
        fresh = await session.get(JobHistory, "fresh-job")
        pending_rows = (
            (
                await session.execute(
                    select(PendingArtifact).where(PendingArtifact.job_id == "fresh-job")
                )
            )
            .scalars()
            .all()
        )
        artifacts = (
            (
                await session.execute(
                    select(Artifact).where(Artifact.job_id == "fresh-job")
                )
            )
            .scalars()
            .all()
        )

    assert old is None
    assert fresh is not None
    assert fresh.status == "active"
    assert len(pending_rows) == 0
    assert len(artifacts) == 1
    assert artifacts[0].name == "artifact"
