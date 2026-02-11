"""Operational alert hooks for function health metrics."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from pydantic import BaseModel
from shared.schemas import FunctionInfo

from server.config import get_settings
from server.services.redis import get_redis

logger = logging.getLogger(__name__)


class FunctionAlertType(StrEnum):
    FAILURE_RATE = "function_failure_rate"
    LATENCY_P95 = "function_latency_p95"
    QUEUE_WAIT_P95 = "function_queue_wait_p95"
    QUEUE_BACKLOG = "function_queue_backlog"


class FunctionAlert(BaseModel):
    """Structured alert payload emitted to webhook targets."""

    type: FunctionAlertType
    function: str
    function_name: str
    value: float
    threshold: float
    metric: str
    at: str
    message: str

    @property
    def fingerprint(self) -> str:
        return f"{self.type.value}:{self.function}"


def build_function_alerts(functions: list[FunctionInfo]) -> list[FunctionAlert]:
    """Build alerts for threshold breaches from function snapshots."""
    settings = get_settings()
    now_iso = datetime.now(UTC).isoformat()
    out: list[FunctionAlert] = []

    for fn in functions:
        failure_rate = 100.0 - fn.success_rate
        if (
            fn.runs_24h >= settings.alert_failure_min_runs_24h
            and failure_rate >= settings.alert_failure_rate_threshold
        ):
            out.append(
                FunctionAlert(
                    type=FunctionAlertType.FAILURE_RATE,
                    function=fn.key,
                    function_name=fn.name,
                    value=round(failure_rate, 2),
                    threshold=settings.alert_failure_rate_threshold,
                    metric="failure_rate_pct",
                    at=now_iso,
                    message=(
                        f"{fn.name} failure rate {failure_rate:.1f}% exceeds "
                        f"threshold {settings.alert_failure_rate_threshold:.1f}%"
                    ),
                )
            )

        if (
            fn.p95_duration_ms is not None
            and fn.p95_duration_ms >= settings.alert_p95_duration_ms_threshold
        ):
            out.append(
                FunctionAlert(
                    type=FunctionAlertType.LATENCY_P95,
                    function=fn.key,
                    function_name=fn.name,
                    value=round(float(fn.p95_duration_ms), 2),
                    threshold=settings.alert_p95_duration_ms_threshold,
                    metric="p95_duration_ms",
                    at=now_iso,
                    message=(
                        f"{fn.name} p95 duration {fn.p95_duration_ms:.0f}ms exceeds "
                        f"threshold {settings.alert_p95_duration_ms_threshold:.0f}ms"
                    ),
                )
            )

        if (
            fn.p95_wait_ms is not None
            and fn.p95_wait_ms >= settings.alert_p95_wait_ms_threshold
        ):
            out.append(
                FunctionAlert(
                    type=FunctionAlertType.QUEUE_WAIT_P95,
                    function=fn.key,
                    function_name=fn.name,
                    value=round(float(fn.p95_wait_ms), 2),
                    threshold=settings.alert_p95_wait_ms_threshold,
                    metric="p95_queue_wait_ms",
                    at=now_iso,
                    message=(
                        f"{fn.name} p95 queue wait {fn.p95_wait_ms:.0f}ms exceeds "
                        f"threshold {settings.alert_p95_wait_ms_threshold:.0f}ms"
                    ),
                )
            )

        if fn.queue_backlog >= settings.alert_queue_backlog_threshold:
            out.append(
                FunctionAlert(
                    type=FunctionAlertType.QUEUE_BACKLOG,
                    function=fn.key,
                    function_name=fn.name,
                    value=float(fn.queue_backlog),
                    threshold=float(settings.alert_queue_backlog_threshold),
                    metric="queue_backlog_count",
                    at=now_iso,
                    message=(
                        f"{fn.name} queue backlog {fn.queue_backlog} exceeds "
                        f"threshold {settings.alert_queue_backlog_threshold}"
                    ),
                )
            )

    return out


async def emit_function_alerts(functions: list[FunctionInfo]) -> int:
    """
    Emit threshold-based function alerts to a configured webhook.

    Returns number of alerts sent.
    """
    settings = get_settings()
    webhook = settings.alert_webhook_url
    if not webhook:
        return 0

    alerts = build_function_alerts(functions)
    if not alerts:
        return 0

    redis_client = None
    try:
        redis_client = await get_redis()
    except RuntimeError:
        redis_client = None

    selected: list[FunctionAlert] = []
    cooldown = max(1, settings.alert_cooldown_seconds)
    for alert in alerts:
        if redis_client is None:
            selected.append(alert)
            continue
        key = f"upnext:alerts:function:{alert.fingerprint}"
        try:
            was_set = await redis_client.set(key, alert.at, nx=True, ex=cooldown)
            if was_set:
                selected.append(alert)
        except Exception:
            selected.append(alert)

    if not selected:
        return 0

    payload = {
        "source": "upnext-server",
        "at": datetime.now(UTC).isoformat(),
        "alerts": [alert.model_dump() for alert in selected],
    }
    timeout_seconds = max(0.1, settings.alert_webhook_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(webhook, json=payload)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to deliver alert webhook: %s", exc)
        return 0

    return len(selected)
