"""Health and operational contract payloads."""

from pydantic import BaseModel, Field


class AlertDeliveryStats(BaseModel):
    """Operational alert delivery counters surfaced by /health."""

    attempted: int = 0
    sent: int = 0
    failures: int = 0
    skipped_cooldown: int = 0
    last_attempt_at: str | None = None
    last_sent_at: str | None = None
    last_error: str | None = None


class DependencyHealth(BaseModel):
    """Readiness status for a dependency."""

    status: str = "ok"
    detail: str | None = None


class ReadinessMetrics(BaseModel):
    """Dependency readiness states surfaced by health endpoints."""

    database: DependencyHealth = Field(default_factory=DependencyHealth)
    redis: DependencyHealth = Field(
        default_factory=lambda: DependencyHealth(
            status="skipped",
            detail="UPNEXT_REDIS_URL not set",
        )
    )


class HealthMetrics(BaseModel):
    """Structured health metrics payload."""

    alerts: AlertDeliveryStats = Field(default_factory=AlertDeliveryStats)
    readiness: ReadinessMetrics = Field(default_factory=ReadinessMetrics)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str
    features: list[str] = Field(default_factory=list)
    metrics: HealthMetrics = Field(default_factory=HealthMetrics)


__all__ = [
    "AlertDeliveryStats",
    "DependencyHealth",
    "HealthMetrics",
    "HealthResponse",
    "ReadinessMetrics",
]
