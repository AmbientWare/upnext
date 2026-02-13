"""Typed stream-envelope contracts shared between writers and readers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.contracts.events import EventType


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str):
        parsed = json.loads(value)
    elif isinstance(value, dict):
        parsed = value
    else:
        raise ValueError("expected JSON object")
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


class StatusStreamEvent(BaseModel):
    """Envelope written by worker status publisher to Redis stream entries."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    job_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    ts: float | None = Field(default=None, ge=0)

    @field_validator("data", mode="before")
    @classmethod
    def _parse_data(cls, value: Any) -> dict[str, Any]:
        return _json_object(value)


class ApiRequestStreamEvent(BaseModel):
    """Envelope written by API tracking middleware to request-events stream."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["api.request"] | None = None
    id: str | None = None
    at: str | None = None
    api_name: str | None = None
    method: str | None = None
    path: str | None = None
    status: int | None = None
    latency_ms: float | None = None
    instance_id: str | None = None
    sampled: bool | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def _parse_data(cls, value: Any) -> dict[str, Any]:
        return _json_object(value)

    def to_request_payload(self, event_id: str) -> dict[str, Any]:
        """Merge top-level and nested payload fields for ApiRequestEvent parsing."""
        payload: dict[str, Any] = dict(self.data)

        if not payload.get("id"):
            payload["id"] = self.id or event_id
        if not payload.get("at"):
            payload["at"] = self.at or datetime.now(UTC).isoformat()
        if not payload.get("api_name"):
            payload["api_name"] = self.api_name
        if not payload.get("method"):
            payload["method"] = (self.method or "GET").upper()
        if not payload.get("path"):
            payload["path"] = self.path or "/"
        if payload.get("status") is None:
            payload["status"] = self.status
        if payload.get("latency_ms") is None:
            payload["latency_ms"] = self.latency_ms
        if payload.get("instance_id") is None:
            payload["instance_id"] = self.instance_id
        if payload.get("sampled") is None:
            payload["sampled"] = bool(self.sampled) if self.sampled is not None else False

        return payload


class WorkerSignalStreamEvent(BaseModel):
    """Envelope published by workers for dashboard refresh signaling."""

    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "worker.heartbeat",
        "worker.definition.updated",
        "worker.stopped",
    ]
    at: str | None = None
    worker_id: str | None = None
    worker_name: str | None = None


__all__ = [
    "StatusStreamEvent",
    "ApiRequestStreamEvent",
    "WorkerSignalStreamEvent",
]

