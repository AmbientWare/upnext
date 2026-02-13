from __future__ import annotations

from dataclasses import dataclass

import pytest
import server.services.operations.alerts as alerts_module
from fakeredis.aioredis import FakeRedis
from shared.contracts import FunctionInfo, FunctionType


@dataclass
class _AlertSettings:
    alert_webhook_url: str | None = "https://example.test/hooks/upnext"
    alert_webhook_timeout_seconds: float = 1.0
    alert_cooldown_seconds: int = 300
    alert_failure_min_runs_24h: int = 10
    alert_failure_rate_threshold: float = 20.0
    alert_p95_duration_ms_threshold: float = 30_000.0
    alert_p95_wait_ms_threshold: float = 10_000.0
    alert_queue_backlog_threshold: int = 100


def _function(**kwargs) -> FunctionInfo:  # type: ignore[no-untyped-def]
    base = FunctionInfo(
        key="fn.a",
        name="fn-a",
        type=FunctionType.TASK,
    )
    return base.model_copy(update=kwargs)


def test_build_function_alerts_emits_expected_types(monkeypatch) -> None:
    monkeypatch.setattr(alerts_module, "get_settings", lambda: _AlertSettings())

    fn = _function(
        runs_24h=50,
        success_rate=70.0,
        p95_duration_ms=35_000.0,
        p95_wait_ms=12_000.0,
        queue_backlog=120,
    )
    alerts = alerts_module.build_function_alerts([fn])
    alert_types = {item.type.value for item in alerts}
    assert alert_types == {
        "function_failure_rate",
        "function_latency_p95",
        "function_queue_wait_p95",
        "function_queue_backlog",
    }


@pytest.mark.asyncio
async def test_emit_function_alerts_respects_redis_cooldown(monkeypatch) -> None:
    settings = _AlertSettings()
    monkeypatch.setattr(alerts_module, "get_settings", lambda: settings)

    fake_redis = FakeRedis(decode_responses=True)

    async def _get_redis() -> FakeRedis:
        return fake_redis

    monkeypatch.setattr(alerts_module, "get_redis", _get_redis)

    sample_alert = alerts_module.FunctionAlert(
        type=alerts_module.FunctionAlertType.FAILURE_RATE,
        function="fn.a",
        function_name="fn-a",
        value=30.0,
        threshold=20.0,
        metric="failure_rate_pct",
        at="2026-02-11T00:00:00Z",
        message="fn-a failure rate high",
    )
    monkeypatch.setattr(
        alerts_module,
        "build_function_alerts",
        lambda _functions: [sample_alert],
    )

    sent_payloads: list[dict] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args) -> None:  # type: ignore[no-untyped-def]
            return None

        async def post(self, url: str, json: dict) -> _Response:  # noqa: A002
            sent_payloads.append({"url": url, "json": json, "timeout": self.timeout})
            return _Response()

    monkeypatch.setattr(alerts_module.httpx, "AsyncClient", _Client)

    first = await alerts_module.emit_function_alerts([_function()])
    second = await alerts_module.emit_function_alerts([_function()])

    assert first == 1
    assert second == 0
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["url"] == settings.alert_webhook_url
    assert sent_payloads[0]["json"]["alerts"][0]["type"] == "function_failure_rate"

    await fake_redis.aclose()
