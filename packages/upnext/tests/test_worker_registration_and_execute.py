from __future__ import annotations

import json

import pytest
from shared.keys.workers import FUNCTION_KEY_PREFIX, WORKER_DEF_PREFIX
from shared.contracts import MissedRunPolicy
from upnext.config import ThroughputMode, get_settings
from upnext.sdk.worker import Worker


class _NoopJobProcessor:
    def __init__(self, *args, **kwargs) -> None:
        self.active_job_count = 0
        self.jobs_processed = 0
        self.jobs_failed = 0

    async def start(self) -> None:
        return None

    async def stop(self, timeout: float = 30.0) -> None:
        return None


@pytest.mark.asyncio
async def test_worker_writes_worker_and_function_definitions(
    fake_redis, monkeypatch
) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )
    monkeypatch.setattr("upnext.sdk.worker.JobProcessor", _NoopJobProcessor)

    worker = Worker(name="writer-worker")

    @worker.task(
        name="health_check",
        retries=2,
        retry_delay=3,
        timeout=45,
        rate_limit="25/m",
        max_concurrency=3,
        routing_group="ops",
        group_max_concurrency=5,
    )
    async def health_check() -> str:
        return "ok"

    handle = worker.tasks["health_check"]

    worker.initialize(redis_url="redis://ignored")
    await worker.start()
    try:
        worker_def_raw = await fake_redis.get(f"{WORKER_DEF_PREFIX}:writer-worker")
        assert worker_def_raw is not None
        worker_def = json.loads(worker_def_raw)
        assert worker_def["name"] == "writer-worker"
        assert worker_def["functions"] == [handle.function_key]

        function_def_raw = await fake_redis.get(
            f"{FUNCTION_KEY_PREFIX}:{handle.function_key}"
        )
        assert function_def_raw is not None
        function_def = json.loads(function_def_raw)
        assert function_def["key"] == handle.function_key
        assert function_def["name"] == "health_check"
        assert function_def["timeout"] == 45
        assert function_def["rate_limit"] == "25/m"
        assert function_def["max_concurrency"] == 3
        assert function_def["routing_group"] == "ops"
        assert function_def["group_max_concurrency"] == 5
    finally:
        await worker.stop(timeout=0.1)


@pytest.mark.asyncio
async def test_execute_helper_accepts_display_name_and_function_key(
    fake_redis, monkeypatch
) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )

    worker = Worker(name="execute-worker", redis_url="redis://ignored")

    @worker.task(name="add")
    async def add(x: int, y: int) -> int:
        return x + y

    result_by_name = await worker.execute("add", {"x": 1, "y": 2})
    result_by_key = await worker.execute(add.function_key, {"x": 4, "y": 5})

    assert result_by_name == 3
    assert result_by_key == 9

    events = await fake_redis.xrange("upnext:status:events", count=20)
    event_types = [row[1][b"type"].decode() for row in events]
    assert event_types.count("job.started") == 2
    assert event_types.count("job.completed") == 2


@pytest.mark.asyncio
async def test_worker_writes_cron_policy_fields(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )
    monkeypatch.setattr("upnext.sdk.worker.JobProcessor", _NoopJobProcessor)

    worker = Worker(name="cron-policy-worker")

    @worker.cron(
        "* * * * *",
        name="tick",
        missed_run_policy=MissedRunPolicy.SKIP,
        max_catch_up_seconds=120,
    )
    async def tick() -> None:
        return None

    worker.initialize(redis_url="redis://ignored")
    await worker.start()
    try:
        cron_key = worker.crons[0].key
        function_def_raw = await fake_redis.get(f"{FUNCTION_KEY_PREFIX}:{cron_key}")
        assert function_def_raw is not None
        cron_def = json.loads(function_def_raw)

        assert cron_def["type"] == "cron"
        assert cron_def["missed_run_policy"] == "skip"
        assert cron_def["max_catch_up_seconds"] == 120
    finally:
        await worker.stop(timeout=0.1)


def test_worker_cron_default_policy_is_latest_only() -> None:
    worker = Worker(name="cron-default-policy")

    @worker.cron("* * * * *", name="default_tick")
    async def default_tick() -> None:
        return None

    assert worker.crons[0].missed_run_policy == MissedRunPolicy.LATEST_ONLY


def test_worker_profile_defaults_shape_queue_tuning(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )

    get_settings.cache_clear()
    monkeypatch.setenv(
        "UPNEXT_QUEUE_RUNTIME_PROFILE",
        ThroughputMode.SAFE.value,
    )
    safe_worker = Worker(name="safe-worker", concurrency=8, redis_url="redis://ignored")
    safe_worker.initialize(redis_url="redis://ignored")
    safe_queue = safe_worker._queue_backend  # noqa: SLF001
    assert safe_queue._batch_size == 100  # noqa: SLF001
    assert safe_queue._inbox_size == 1000  # noqa: SLF001
    assert safe_queue._flush_interval == 0.005  # noqa: SLF001
    assert safe_queue._stream_maxlen == 0  # noqa: SLF001

    get_settings.cache_clear()
    monkeypatch.setenv(
        "UPNEXT_QUEUE_RUNTIME_PROFILE",
        ThroughputMode.THROUGHPUT.value,
    )
    throughput_worker = Worker(
        name="throughput-worker",
        concurrency=8,
        redis_url="redis://ignored",
    )
    throughput_worker.initialize(redis_url="redis://ignored")
    throughput_queue = throughput_worker._queue_backend  # noqa: SLF001
    assert throughput_queue._batch_size == 200  # noqa: SLF001
    assert throughput_queue._inbox_size == 2000  # noqa: SLF001
    assert throughput_queue._flush_interval == 0.02  # noqa: SLF001
    assert throughput_queue._stream_maxlen == 200_000  # noqa: SLF001

    get_settings.cache_clear()


def test_worker_explicit_prefetch_adds_buffer_above_concurrency(
    fake_redis, monkeypatch
) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )

    worker = Worker(
        name="prefetch-capped-worker",
        concurrency=16,
        prefetch=3,
        redis_url="redis://ignored",
    )
    worker.initialize(redis_url="redis://ignored")
    queue = worker._queue_backend  # noqa: SLF001
    assert queue._inbox_size == 19  # noqa: SLF001


def test_worker_queue_kwargs_override_profile_defaults(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )
    get_settings.cache_clear()
    monkeypatch.setenv("UPNEXT_QUEUE_RUNTIME_PROFILE", ThroughputMode.SAFE.value)

    worker = Worker(
        name="tuned-worker",
        concurrency=16,
        redis_url="redis://ignored",
        queue_batch_size=64,
        queue_inbox_size=128,
        queue_outbox_size=256,
        queue_flush_interval_ms=15.0,
        queue_claim_timeout_ms=45_000,
        queue_job_ttl_seconds=99,
        queue_result_ttl_seconds=88,
        queue_stream_maxlen=77,
        queue_dlq_stream_maxlen=66,
    )
    worker.initialize(redis_url="redis://ignored")
    queue = worker._queue_backend  # noqa: SLF001
    assert queue._batch_size == 64  # noqa: SLF001
    assert queue._inbox_size == 128  # noqa: SLF001
    assert queue._outbox_size == 256  # noqa: SLF001
    assert queue._flush_interval == 0.015  # noqa: SLF001
    assert queue._claim_timeout_ms == 45_000  # noqa: SLF001
    assert queue._job_ttl_seconds == 99  # noqa: SLF001
    assert queue._result_ttl_seconds == 88  # noqa: SLF001
    assert queue._stream_maxlen == 77  # noqa: SLF001
    assert queue._dlq_stream_maxlen == 66  # noqa: SLF001
    get_settings.cache_clear()


def test_worker_queue_kwargs_validate_ranges(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        "upnext.sdk.worker.create_redis_client", lambda _url: fake_redis
    )

    with pytest.raises(ValueError, match="queue_batch_size must be >= 1"):
        Worker(
            name="invalid-batch",
            redis_url="redis://ignored",
            queue_batch_size=0,
        ).initialize(redis_url="redis://ignored")

    with pytest.raises(ValueError, match="queue_stream_maxlen must be >= 0"):
        Worker(
            name="invalid-stream",
            redis_url="redis://ignored",
            queue_stream_maxlen=-1,
        ).initialize(redis_url="redis://ignored")

    with pytest.raises(ValueError, match="queue_flush_interval_ms must be > 0"):
        Worker(
            name="invalid-flush",
            redis_url="redis://ignored",
            queue_flush_interval_ms=0,
        ).initialize(redis_url="redis://ignored")


def test_worker_autodiscover(tmp_path) -> None:
    """autodiscover() imports all modules in a package to trigger registration."""
    import sys

    # Create a temp package with submodules
    pkg_dir = tmp_path / "discoverpkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "orders.py").write_text("LOADED = True\n")
    (pkg_dir / "notifications.py").write_text("LOADED = True\n")

    # Nested subpackage
    sub_dir = pkg_dir / "sub"
    sub_dir.mkdir()
    (sub_dir / "__init__.py").write_text("")
    (sub_dir / "deep.py").write_text("LOADED = True\n")

    sys.path.insert(0, str(tmp_path))
    try:
        worker = Worker(name="discover-worker")
        assert "discoverpkg.orders" not in sys.modules
        assert "discoverpkg.notifications" not in sys.modules
        assert "discoverpkg.sub.deep" not in sys.modules

        worker.autodiscover("discoverpkg")

        assert "discoverpkg.orders" in sys.modules
        assert "discoverpkg.notifications" in sys.modules
        assert "discoverpkg.sub.deep" in sys.modules
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("discoverpkg"):
                del sys.modules[key]


def test_worker_autodiscover_packages_init_param(tmp_path) -> None:
    """autodiscover_packages in __init__ triggers discovery at construction."""
    import sys

    pkg_dir = tmp_path / "initpkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "tasks.py").write_text("LOADED = True\n")

    sys.path.insert(0, str(tmp_path))
    try:
        assert "initpkg.tasks" not in sys.modules
        Worker(name="init-discover", autodiscover_packages=["initpkg"])
        assert "initpkg.tasks" in sys.modules
    finally:
        sys.path.remove(str(tmp_path))
        for key in list(sys.modules):
            if key.startswith("initpkg"):
                del sys.modules[key]
