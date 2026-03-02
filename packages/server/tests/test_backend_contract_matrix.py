from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import pytest_asyncio
from server.backends.base.utils import hash_api_key
from server.backends.redis.session import RedisBackend
from server.backends.session_context import RepositorySession
from server.backends.sql.base import BaseSqlBackend


def _job_payload(
    job_id: str,
    *,
    status: str,
    created_at: datetime,
    parent_id: str | None = None,
    root_id: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "job_id": job_id,
        "job_key": job_id,
        "function": "fn.contract",
        "function_name": "contract",
        "status": status,
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "parent_id": parent_id,
        "root_id": root_id or job_id,
    }


_BACKEND_PARAMS = [
    pytest.param("sqlite", id="sqlite"),
    pytest.param("redis", id="redis"),
    pytest.param("postgres", marks=pytest.mark.integration, id="postgres"),
]


@pytest_asyncio.fixture(params=_BACKEND_PARAMS)
async def repo_session(
    request: pytest.FixtureRequest,
    sqlite_db,
    fake_redis,
) -> AsyncIterator[tuple[str, RepositorySession[object]]]:
    if request.param == "sqlite":
        backend = sqlite_db
        async with backend.session() as tx:
            yield request.param, tx
        return

    if request.param == "redis":
        backend = RedisBackend("redis://unused")
        backend._redis = cast(Any, fake_redis)  # noqa: SLF001
        async with backend.session() as tx:
            yield request.param, tx
        return

    database_url = os.getenv("UPNEXT_TEST_POSTGRES_URL") or os.getenv(
        "UPNEXT_TEST_DATABASE_URL"
    )
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip(
            "Set UPNEXT_TEST_POSTGRES_URL (or UPNEXT_TEST_DATABASE_URL with "
            "postgresql://) to run postgres backend contract tests."
        )

    backend = BaseSqlBackend(database_url)
    await backend.connect()
    await backend.drop_tables()
    await backend.create_tables()
    try:
        async with backend.session() as tx:
            yield request.param, tx
    finally:
        await backend.drop_tables()
        await backend.disconnect()


@pytest.mark.asyncio
async def test_jobs_contract_record_list_stats(
    repo_session: tuple[str, RepositorySession[object]],
) -> None:
    backend_name, tx = repo_session
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    await tx.jobs.record_job(
        _job_payload(
            "job-root",
            status="complete",
            created_at=base,
            started_at=base,
            completed_at=base + timedelta(seconds=2),
        )
    )
    await tx.jobs.record_job(
        _job_payload(
            "job-child",
            status="failed",
            created_at=base + timedelta(seconds=10),
            parent_id="job-root",
            root_id="job-root",
            started_at=base + timedelta(seconds=10),
            completed_at=base + timedelta(seconds=12),
        )
    )
    await tx.flush()

    root = await tx.jobs.get_by_id("job-root")
    assert root is not None, backend_name

    subtree = await tx.jobs.list_job_subtree("job-root")
    assert [job.id for job in subtree] == ["job-root", "job-child"], backend_name

    failed_rows = await tx.jobs.list_jobs(
        function="fn.contract", status="failed", limit=10
    )
    assert [row.id for row in failed_rows] == ["job-child"], backend_name

    count = await tx.jobs.count_jobs(function="fn.contract")
    assert count == 2, backend_name

    stats = await tx.jobs.get_stats(function="fn.contract")
    assert stats.total == 2, backend_name
    assert stats.success_count == 1, backend_name
    assert stats.failure_count == 1, backend_name

    durations = await tx.jobs.get_durations(
        function="fn.contract",
        start_date=base - timedelta(minutes=1),
    )
    rounded = sorted(round(v) for v in durations)
    assert rounded == [2000, 2000], backend_name


@pytest.mark.asyncio
async def test_artifacts_contract_create_promote_delete(
    repo_session: tuple[str, RepositorySession[object]],
) -> None:
    backend_name, tx = repo_session
    now = datetime(2026, 1, 1, 12, 10, tzinfo=UTC)
    job_id = "job-artifacts"

    await tx.jobs.record_job(_job_payload(job_id, status="active", created_at=now))
    await tx.flush()

    artifact = await tx.artifacts.create(
        job_id=job_id,
        name="result.json",
        artifact_type="json",
        data={"ok": True},
    )
    pending = await tx.artifacts.create_pending(
        job_id=job_id,
        name="later.json",
        artifact_type="json",
        data={"queued": True},
    )
    await tx.flush()

    initial = await tx.artifacts.list_by_job(job_id)
    assert any(row.id == artifact.id for row in initial), backend_name
    assert all(row.id != pending.id for row in initial), backend_name

    promoted = await tx.artifacts.promote_pending_for_job_with_artifacts(job_id)
    assert len(promoted) == 1, backend_name

    listed = await tx.artifacts.list_by_job(job_id)
    assert len(listed) == 2, backend_name

    deleted = await tx.artifacts.delete(artifact.id)
    deleted_again = await tx.artifacts.delete(artifact.id)
    assert deleted is True, backend_name
    assert deleted_again is False, backend_name


@pytest.mark.asyncio
async def test_artifacts_contract_promote_ready_pending_requires_job_row(
    repo_session: tuple[str, RepositorySession[object]],
) -> None:
    backend_name, tx = repo_session
    now = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    missing_job_id = "job-pending-contract"

    await tx.artifacts.create_pending(
        job_id=missing_job_id,
        name="pending-only.json",
        artifact_type="json",
        data={"pending": True},
    )
    await tx.flush()

    promoted_before = await tx.artifacts.promote_ready_pending(limit=100)
    assert promoted_before == 0, backend_name

    await tx.jobs.record_job(
        _job_payload(missing_job_id, status="queued", created_at=now)
    )
    await tx.flush()

    promoted_after = await tx.artifacts.promote_ready_pending(limit=100)
    assert promoted_after == 1, backend_name


@pytest.mark.asyncio
async def test_auth_contract_user_api_keys_and_seed(
    repo_session: tuple[str, RepositorySession[object]],
) -> None:
    backend_name, tx = repo_session

    user = await tx.auth.create_user("alice", is_admin=False)
    with pytest.raises(ValueError):
        await tx.auth.create_user("alice", is_admin=False)

    created_key, raw_key = await tx.auth.create_api_key(user.id, "ci")
    found_by_hash = await tx.auth.get_api_key_by_hash(hash_api_key(raw_key))
    assert found_by_hash is not None, backend_name
    assert found_by_hash.id == created_key.id, backend_name

    toggled = await tx.auth.toggle_api_key(created_key.id, False)
    assert toggled is not None, backend_name
    assert toggled.is_active is False, backend_name

    rotated_key, rotated_raw = await tx.auth.rotate_api_key(user.id)
    assert rotated_key.id != created_key.id, backend_name
    assert await tx.auth.get_api_key_by_hash(hash_api_key(rotated_raw)) is not None

    await tx.auth.seed_admin_api_key("upnxt_contract_seed_key")
    await tx.auth.seed_admin_api_key("upnxt_contract_seed_key")
    admin = await tx.auth.get_user_by_username("admin")
    assert admin is not None and admin.is_admin is True, backend_name

    users_with_counts = await tx.auth.list_users()
    users_by_name = {u.username: count for u, count in users_with_counts}
    assert "alice" in users_by_name, backend_name
    assert "admin" in users_by_name, backend_name

    deleted = await tx.auth.delete_user(user.id)
    deleted_again = await tx.auth.delete_user(user.id)
    assert deleted is True, backend_name
    assert deleted_again is False, backend_name


@pytest.mark.asyncio
async def test_secrets_contract_crud(
    repo_session: tuple[str, RepositorySession[object]],
) -> None:
    backend_name, tx = repo_session

    secret = await tx.secrets.create_secret("stripe", {"api_key": "sk_test"})
    with pytest.raises(ValueError):
        await tx.secrets.create_secret("stripe", {"api_key": "dup"})

    listed = await tx.secrets.list_secrets()
    assert any(row.id == secret.id for row in listed), backend_name

    fetched = await tx.secrets.get_secret_by_name("stripe")
    assert fetched is not None, backend_name
    assert tx.secrets.decrypt_secret(fetched) == {"api_key": "sk_test"}, backend_name

    updated = await tx.secrets.update_secret(
        secret.id,
        name="stripe_live",
        data={"api_key": "sk_live"},
    )
    assert updated is not None, backend_name
    assert updated.name == "stripe_live", backend_name

    by_new_name = await tx.secrets.get_secret_by_name("stripe_live")
    assert by_new_name is not None, backend_name
    assert tx.secrets.decrypt_secret(by_new_name) == {"api_key": "sk_live"}

    deleted = await tx.secrets.delete_secret(secret.id)
    deleted_again = await tx.secrets.delete_secret(secret.id)
    assert deleted is True, backend_name
    assert deleted_again is False, backend_name
