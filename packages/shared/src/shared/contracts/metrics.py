"""Queue metrics contract payloads for external monitoring."""

from pydantic import BaseModel, Field


class FunctionQueueMetrics(BaseModel):
    """Per-function queue depth metrics."""

    function: str
    waiting: int = 0
    claimed: int = 0
    backlog: int = 0
    dlq_entries: int = 0


class QueueMetricsTotals(BaseModel):
    """Aggregate queue totals."""

    running: int = 0
    waiting: int = 0
    claimed: int = 0
    backlog: int = 0
    capacity: int = 0
    dlq_entries: int = 0


class QueueMetricsResponse(BaseModel):
    """Queue metrics response for external monitoring."""

    functions: list[FunctionQueueMetrics] = Field(default_factory=list)
    totals: QueueMetricsTotals = Field(default_factory=QueueMetricsTotals)


__all__ = [
    "FunctionQueueMetrics",
    "QueueMetricsResponse",
    "QueueMetricsTotals",
]
