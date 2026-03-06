from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
import server.config as config_module
import server.main as main_module
import server.services.apis.instances as api_instances_module
import server.services.redis as redis_module
from fastapi import FastAPI
from server.backends.types import PersistenceBackends
from server.runtime_scope import RuntimeModes
from shared.keys import status_events_stream_key
from shared._version import __version__ as shared_version


@dataclass
class _SettingsStub:
    backend: PersistenceBackends = PersistenceBackends.SQLITE
    redis_url: str | None = None
    cleanup_retention_hours: int = 7 * 24
    host: str = "127.0.0.1"
    port: int = 9000
    version: str = shared_version
    event_subscriber_batch_size: int = 100
    event_subscriber_poll_interval_ms: int = 2000
    event_subscriber_stale_claim_ms: int = 30000
    event_subscriber_invalid_stream: str | None = None
    event_subscriber_invalid_stream_maxlen: int = 10_000
    cleanup_interval_hours: int = 1
    cleanup_pending_retention_hours: int = 24
    cleanup_pending_promote_batch: int = 500
    cleanup_pending_promote_max_loops: int = 20
    cleanup_startup_jitter_seconds: float = 30.0
    alert_poll_interval_seconds: float = 60.0
    auth_enabled: bool = False
    api_key: str | None = None
    runtime_mode: RuntimeModes = RuntimeModes.SELF_HOSTED
    runtime_token_secret: str | None = None
    runtime_session_cookie_name: str = "upnext_runtime_session"
    runtime_session_cookie_secure: bool = False
    runtime_session_cookie_samesite: str = "lax"
    runtime_session_cookie_domain: str | None = None
    runtime_session_ttl_seconds: int = 900
    runtime_default_session_enabled: bool = False
    runtime_default_subject: str = "default-user"
    runtime_default_email: str | None = "default@upnext.local"
    runtime_default_name: str | None = "Default User"
    is_production: bool = False
    cors_allow_origins_list: list[str] = field(default_factory=lambda: ["*"])
    is_development: bool = True
    workspace_id: str = "local"

    @property
    def is_cloud_runtime(self) -> bool:
        return self.runtime_mode == RuntimeModes.CLOUD_RUNTIME

    @property
    def normalized_workspace_id(self) -> str:
        return self.workspace_id

    @property
    def allow_runtime_default_session(self) -> bool:
        return self.runtime_default_session_enabled or self.is_development

    @property
    def status_events_stream(self) -> str:
        return status_events_stream_key(workspace_id=self.normalized_workspace_id)

    @property
    def effective_invalid_events_stream(self) -> str:
        return self.event_subscriber_invalid_stream


class _FakeDatabase:
    def __init__(
        self,
        *,
        missing_tables: list[str] | None = None,
        backend_name: str = "sqlite",
    ) -> None:
        self.backend_name = backend_name
        self.connected = 0
        self.disconnected = 0
        self.created_tables = 0
        self.checked_tables = 0
        self.missing_tables = missing_tables or []

    async def connect(self) -> None:
        self.connected += 1

    async def disconnect(self) -> None:
        self.disconnected += 1

    async def create_tables(self) -> None:
        self.created_tables += 1

    async def get_missing_tables(self, required_tables: set[str]) -> list[str]:
        self.checked_tables += 1
        assert required_tables == {
            "job_history",
            "artifacts",
            "pending_artifacts",
            "secrets",
        }
        return list(self.missing_tables)

    async def prepare_startup(self, required_tables: set[str]) -> None:
        if self.backend_name == "sqlite":
            await self.create_tables()
            return
        missing = await self.get_missing_tables(required_tables)
        if missing:
            raise RuntimeError(
                "Database schema is missing required tables: " + ", ".join(missing)
            )

    @asynccontextmanager
    async def session(self):
        yield object()


class _FakeCleanupService:
    instances: list[_FakeCleanupService] = []

    def __init__(self, redis_client: Any = None, **kwargs: Any) -> None:
        self.redis_client = redis_client
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeStreamSubscriber:
    instances: list[_FakeStreamSubscriber] = []

    def __init__(self, redis_client: Any, config: Any = None) -> None:
        self.redis_client = redis_client
        self.config = config
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeAlertEmitterService:
    instances: list[_FakeAlertEmitterService] = []

    def __init__(self, interval_seconds: float = 60.0) -> None:
        self.interval_seconds = interval_seconds
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeRedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _ScanRedis:
    def __init__(self, values: dict[str, str | None]) -> None:
        self._values = values

    async def scan_iter(self, match: str, count: int = 100):  # noqa: ARG002
        for key in sorted(self._values):
            yield key

    async def get(self, key: str) -> str | None:
        return self._values.get(key)


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    config_module.get_settings.cache_clear()
    redis_module._redis_client = None  # type: ignore[attr-defined]
    _FakeCleanupService.instances.clear()
    _FakeStreamSubscriber.instances.clear()
    _FakeAlertEmitterService.instances.clear()


def test_server_settings_defaults_and_flags(monkeypatch) -> None:
    monkeypatch.delenv("UPNEXT_DATABASE_URL", raising=False)
    monkeypatch.delenv("UPNEXT_BACKEND", raising=False)
    monkeypatch.setenv("UPNEXT_ENV", "dev")
    monkeypatch.delenv("UPNEXT_CORS_ALLOW_ORIGINS", raising=False)
    monkeypatch.delenv("UPNEXT_CORS_ALLOW_CREDENTIALS", raising=False)
    settings = config_module.get_settings()

    assert settings.is_development is True
    assert settings.is_production is False
    assert settings.backend == PersistenceBackends.REDIS
    assert settings.effective_database_url is None
    assert settings.is_sql_backend is False
    assert settings.cors_allow_origins_list == ["*"]
    assert settings.cors_allow_credentials is False
    assert config_module.get_settings() is settings


def test_server_settings_database_override(monkeypatch) -> None:
    monkeypatch.setenv("UPNEXT_ENV", "prod")
    monkeypatch.setenv("UPNEXT_BACKEND", "postgres")
    monkeypatch.setenv("UPNEXT_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv(
        "UPNEXT_DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/upnext"
    )
    monkeypatch.setenv(
        "UPNEXT_CORS_ALLOW_ORIGINS",
        "https://app.example.com,https://admin.example.com",
    )
    monkeypatch.setenv("UPNEXT_CORS_ALLOW_CREDENTIALS", "true")
    settings = config_module.get_settings()

    assert settings.is_production is True
    assert settings.is_development is False
    assert settings.backend == PersistenceBackends.POSTGRES
    assert settings.effective_database_url.startswith("postgresql+asyncpg://")
    assert settings.is_sql_backend is True
    assert settings.cors_allow_origins_list == [
        "https://app.example.com",
        "https://admin.example.com",
    ]
    assert settings.cors_allow_credentials is True


def test_server_settings_env_aliases_are_accepted(monkeypatch) -> None:
    monkeypatch.setenv("UPNEXT_ENV", "development")
    settings = config_module.get_settings()
    assert settings.env.value == "dev"
    assert settings.is_development is True

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("UPNEXT_ENV", "production")
    settings = config_module.get_settings()
    assert settings.env.value == "prod"
    assert settings.is_production is True


def test_server_settings_cloud_runtime_requires_non_local_workspace(
    monkeypatch,
) -> None:
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("UPNEXT_RUNTIME_MODE", "cloud_runtime")
    monkeypatch.setenv("UPNEXT_WORKSPACE_ID", "local")
    monkeypatch.setenv("UPNEXT_SECRET_KEY", "test-secret-key")

    with pytest.raises(
        ValueError,
        match="UPNEXT_WORKSPACE_ID must be set to a non-local value",
    ):
        config_module.get_settings()


def test_cleanup_retention_defaults_by_backend(monkeypatch) -> None:
    monkeypatch.setenv("UPNEXT_BACKEND", "redis")
    monkeypatch.delenv("UPNEXT_CLEANUP_RETENTION_HOURS", raising=False)
    settings = config_module.get_settings()
    assert settings.cleanup_retention_hours == 6

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("UPNEXT_BACKEND", "postgres")
    settings = config_module.get_settings()
    assert settings.cleanup_retention_hours == 7 * 24


def test_cleanup_retention_env_overrides_defaults(monkeypatch) -> None:
    monkeypatch.setenv("UPNEXT_BACKEND", "redis")
    monkeypatch.setenv("UPNEXT_CLEANUP_RETENTION_HOURS", "11")
    settings = config_module.get_settings()
    assert settings.cleanup_retention_hours == 11


@pytest.mark.asyncio
async def test_redis_service_connect_get_and_close(monkeypatch) -> None:
    fake_client = _FakeRedisClient()
    monkeypatch.setattr(
        redis_module.redis,
        "from_url",
        lambda _url, decode_responses=True: fake_client,  # noqa: ARG005
    )

    first = await redis_module.connect_redis("redis://first")
    second = await redis_module.connect_redis("redis://second")
    current = await redis_module.get_redis()

    assert first is fake_client
    assert second is fake_client
    assert current is fake_client

    await redis_module.close_redis()
    assert fake_client.closed is True
    assert redis_module._redis_client is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_redis_requires_connection() -> None:
    with pytest.raises(RuntimeError, match="Redis not connected"):
        await redis_module.get_redis()


@pytest.mark.asyncio
async def test_list_api_instances_parses_payloads_and_defaults(monkeypatch) -> None:
    values = {
        "upnext:apis:api-1": json.dumps(
            {
                "id": "api-1",
                "api_name": "orders",
                "started_at": "2026-02-08T10:00:00Z",
                "last_heartbeat": "2026-02-08T10:00:10Z",
                "host": "127.0.0.1",
                "port": 8080,
                "endpoints": ["GET:/orders"],
                "hostname": "host-a",
            }
        ),
        "upnext:apis:api-2": json.dumps(
            {
                "id": "api-2",
                "api_name": "billing",
                "started_at": "2026-02-08T10:00:00Z",
                "last_heartbeat": "2026-02-08T10:00:10Z",
            }
        ),
        "upnext:apis:stale": None,
    }
    fake_redis = _ScanRedis(values)

    async def fake_get_redis() -> _ScanRedis:
        return fake_redis

    monkeypatch.setattr(api_instances_module, "get_redis", fake_get_redis)

    instances = await api_instances_module.list_api_instances()
    by_id = {item.id: item for item in instances}

    assert len(instances) == 2
    assert by_id["api-1"].host == "127.0.0.1"
    assert by_id["api-1"].port == 8080
    assert by_id["api-2"].host == "0.0.0.0"
    assert by_id["api-2"].port == 8000
    assert by_id["api-2"].endpoints == []


@pytest.mark.asyncio
async def test_lifespan_sqlite_path_runs_cleanup_without_redis(monkeypatch) -> None:
    settings = _SettingsStub(
        backend=PersistenceBackends.SQLITE,
        redis_url=None,
    )
    db = _FakeDatabase()

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "get_backend", lambda **_: db)
    monkeypatch.setattr(main_module, "CleanupService", _FakeCleanupService)
    monkeypatch.setattr(main_module, "AlertEmitterService", _FakeAlertEmitterService)
    monkeypatch.setattr(main_module, "StreamSubscriber", _FakeStreamSubscriber)

    async def fail_if_called(_url: str):  # pragma: no cover - defensive guard
        raise AssertionError(
            "connect_redis should not be called when redis_url is unset"
        )

    monkeypatch.setattr(main_module, "connect_redis", fail_if_called)

    async with main_module.lifespan(FastAPI()):
        assert db.connected == 1
        assert db.created_tables == 1
        assert _FakeCleanupService.instances[0].started is True
        assert _FakeAlertEmitterService.instances[0].started is True
        assert _FakeCleanupService.instances[0].redis_client is None
        assert _FakeCleanupService.instances[0].kwargs["retention_hours"] == 7 * 24

    assert db.disconnected == 1
    assert _FakeCleanupService.instances[0].stopped is True
    assert _FakeAlertEmitterService.instances[0].stopped is True
    assert _FakeStreamSubscriber.instances == []


@pytest.mark.asyncio
async def test_lifespan_postgres_missing_tables_fails_fast(monkeypatch) -> None:
    settings = _SettingsStub(
        backend=PersistenceBackends.POSTGRES,
        redis_url=None,
    )
    db = _FakeDatabase(missing_tables=["job_history"], backend_name="postgres")

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "get_backend", lambda **_: db)
    monkeypatch.setattr(main_module, "CleanupService", _FakeCleanupService)
    monkeypatch.setattr(main_module, "AlertEmitterService", _FakeAlertEmitterService)

    with pytest.raises(RuntimeError, match="missing required tables"):
        async with main_module.lifespan(FastAPI()):
            pass

    assert db.connected == 1
    assert db.checked_tables == 1
    assert _FakeCleanupService.instances == []


@pytest.mark.asyncio
async def test_lifespan_with_redis_starts_and_stops_subscriber(monkeypatch) -> None:
    settings = _SettingsStub(
        backend=PersistenceBackends.POSTGRES,
        redis_url="redis://localhost:6379",
    )
    db = _FakeDatabase(missing_tables=[], backend_name="postgres")
    redis_client = object()
    close_calls = {"count": 0}

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "get_backend", lambda **_: db)
    monkeypatch.setattr(main_module, "CleanupService", _FakeCleanupService)
    monkeypatch.setattr(main_module, "AlertEmitterService", _FakeAlertEmitterService)
    monkeypatch.setattr(main_module, "StreamSubscriber", _FakeStreamSubscriber)

    async def fake_connect_redis(_url: str) -> object:
        return redis_client

    async def fake_close_redis() -> None:
        close_calls["count"] += 1

    monkeypatch.setattr(main_module, "connect_redis", fake_connect_redis)
    monkeypatch.setattr(main_module, "close_redis", fake_close_redis)

    async with main_module.lifespan(FastAPI()):
        assert _FakeStreamSubscriber.instances[0].started is True
        assert _FakeStreamSubscriber.instances[0].redis_client is redis_client
        assert _FakeCleanupService.instances[0].redis_client is redis_client
        assert _FakeCleanupService.instances[0].kwargs["interval_hours"] == 1
        assert _FakeAlertEmitterService.instances[0].started is True

    assert _FakeStreamSubscriber.instances[0].stopped is True
    assert _FakeCleanupService.instances[0].stopped is True
    assert _FakeAlertEmitterService.instances[0].stopped is True
    assert close_calls["count"] == 1
    assert db.disconnected == 1


def test_main_uses_settings_for_uvicorn(monkeypatch) -> None:
    settings = _SettingsStub(
        backend=PersistenceBackends.SQLITE,
        redis_url=None,
        host="0.0.0.0",
        port=8080,
    )
    captured: dict[str, Any] = {}

    def fake_run(app_path: str, host: str, port: int) -> None:
        captured["app_path"] = app_path
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr("uvicorn.run", fake_run)

    main_module.main()

    assert captured == {
        "app_path": "server.main:app",
        "host": "0.0.0.0",
        "port": 8080,
    }


def test_app_registers_health_and_api_routes() -> None:
    paths = {getattr(route, "path", "") for route in main_module.app.routes}
    assert "/health" in paths
    assert "/ready" in paths
    assert "/api/v1/jobs" in paths
