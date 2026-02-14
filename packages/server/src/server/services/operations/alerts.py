"""Operational alert hooks for function health metrics."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from pydantic import BaseModel
from shared.contracts import AlertDeliveryStats, FunctionInfo

from server.config import get_settings
from server.services.redis import get_redis

logger = logging.getLogger(__name__)


@dataclass
class _AlertDeliveryStats:
    attempted: int = 0
    sent: int = 0
    failures: int = 0
    skipped_cooldown: int = 0
    last_attempt_at: str | None = None
    last_sent_at: str | None = None
    last_error: str | None = None


_ALERT_DELIVERY_STATS = _AlertDeliveryStats()
_ALERT_FUNCTION_COOLDOWN_PREFIX = "upnext:alerts:function"


class FunctionAlertType(StrEnum):
    FAILURE_RATE = "function_failure_rate"
    LATENCY_P95 = "function_latency_p95"
    QUEUE_WAIT_P95 = "function_queue_wait_p95"
    QUEUE_BACKLOG = "function_queue_backlog"
    INVALID_EVENT_RATE = "invalid_event_rate"


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


def _alert_cooldown_key(fingerprint: str) -> str:
    return f"{_ALERT_FUNCTION_COOLDOWN_PREFIX}:{fingerprint}"


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


def get_alert_delivery_stats() -> AlertDeliveryStats:
    """Return in-process alert delivery counters for diagnostics/health endpoints."""
    return AlertDeliveryStats(
        attempted=_ALERT_DELIVERY_STATS.attempted,
        sent=_ALERT_DELIVERY_STATS.sent,
        failures=_ALERT_DELIVERY_STATS.failures,
        skipped_cooldown=_ALERT_DELIVERY_STATS.skipped_cooldown,
        last_attempt_at=_ALERT_DELIVERY_STATS.last_attempt_at,
        last_sent_at=_ALERT_DELIVERY_STATS.last_sent_at,
        last_error=_ALERT_DELIVERY_STATS.last_error,
    )


async def _emit_alerts(alerts: list[FunctionAlert]) -> int:
    """Deliver alerts to the configured webhook. Returns count sent."""
    if not alerts:
        return 0

    settings = get_settings()
    webhook = settings.alert_webhook_url
    if not webhook:
        return 0

    _ALERT_DELIVERY_STATS.attempted += len(alerts)
    _ALERT_DELIVERY_STATS.last_attempt_at = datetime.now(UTC).isoformat()

    payload = {
        "source": "upnext-server",
        "at": datetime.now(UTC).isoformat(),
        "alerts": [alert.model_dump() for alert in alerts],
    }
    timeout_seconds = max(0.1, settings.alert_webhook_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(webhook, json=payload)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to deliver alert webhook: %s", exc)
        _ALERT_DELIVERY_STATS.failures += len(alerts)
        _ALERT_DELIVERY_STATS.last_error = str(exc)
        return 0

    _ALERT_DELIVERY_STATS.sent += len(alerts)
    _ALERT_DELIVERY_STATS.last_sent_at = datetime.now(UTC).isoformat()
    _ALERT_DELIVERY_STATS.last_error = None
    return len(alerts)


async def emit_function_alerts(functions: list[FunctionInfo]) -> int:
    """
    Emit threshold-based function alerts to a configured webhook.

    Returns number of alerts sent.
    """
    settings = get_settings()
    if not settings.alert_webhook_url:
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
        key = _alert_cooldown_key(alert.fingerprint)
        try:
            was_set = await redis_client.set(key, alert.at, nx=True, ex=cooldown)
            if was_set:
                selected.append(alert)
        except Exception:
            selected.append(alert)

    if not selected:
        _ALERT_DELIVERY_STATS.skipped_cooldown += len(alerts)
        return 0

    return await _emit_alerts(selected)


class AlertEmitterService:
    """Background service that emits function alerts off the request path."""

    def __init__(self, interval_seconds: float = 60.0) -> None:
        self._interval_seconds = max(5.0, interval_seconds)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_invalid_event_total: int = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                # Lazy import to avoid circular imports with route modules.
                from server.routes.functions import collect_functions_snapshot

                functions = await collect_functions_snapshot(type=None)
                await emit_function_alerts(functions)
                await self._check_invalid_event_rate()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - best effort background loop
                logger.debug("Alert emitter tick failed: %s", exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )
            except TimeoutError:
                continue

    async def _check_invalid_event_rate(self) -> None:
        """Check subscriber discard counters and emit alert on high rate."""
        from server.services.events import get_event_processing_stats

        settings = get_settings()
        threshold = settings.alert_invalid_event_rate_threshold
        if threshold <= 0:
            return

        stats = get_event_processing_stats()
        current_total = stats.total_discarded
        delta = current_total - self._last_invalid_event_total
        self._last_invalid_event_total = current_total

        if delta >= threshold:
            logger.warning(
                "High invalid event rate: %d discarded events in last poll interval "
                "(threshold: %d). Breakdown: %s",
                delta,
                threshold,
                stats,
            )
            # Emit as a system-level alert to webhook.
            webhook = settings.alert_webhook_url
            if not webhook:
                return
            now_iso = datetime.now(UTC).isoformat()
            alert = FunctionAlert(
                type=FunctionAlertType.INVALID_EVENT_RATE,
                function="__system__",
                function_name="Event Subscriber",
                value=float(delta),
                threshold=float(threshold),
                metric="invalid_events_per_interval",
                at=now_iso,
                message=(
                    f"Invalid event rate {delta} exceeds threshold {threshold} "
                    f"per poll interval"
                ),
            )
            await _emit_alerts([alert])
