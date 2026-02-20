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


class QueueHealthSummary(BaseModel):
    """Queue depth summary surfaced by health endpoints."""

    running: int = 0
    waiting: int = 0
    claimed: int = 0
    backlog: int = 0
    capacity: int = 0


class EventProcessingStats(BaseModel):
    """Subscriber event processing counters surfaced by health endpoints."""

    invalid_envelope: int = 0
    invalid_payload: int = 0
    unsupported_type: int = 0

    @property
    def total_discarded(self) -> int:
        return self.invalid_envelope + self.invalid_payload + self.unsupported_type


class HealthMetrics(BaseModel):
    """Structured health metrics payload."""

    alerts: AlertDeliveryStats = Field(default_factory=AlertDeliveryStats)
    readiness: ReadinessMetrics = Field(default_factory=ReadinessMetrics)
    queue: QueueHealthSummary = Field(default_factory=QueueHealthSummary)
    events: EventProcessingStats = Field(default_factory=EventProcessingStats)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str
    features: list[str] = Field(default_factory=list)
    metrics: HealthMetrics = Field(default_factory=HealthMetrics)


__all__ = [
    "AlertDeliveryStats",
    "DependencyHealth",
    "EventProcessingStats",
    "HealthMetrics",
    "HealthResponse",
    "QueueHealthSummary",
    "ReadinessMetrics",
]
