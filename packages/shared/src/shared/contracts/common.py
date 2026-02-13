"""Shared contract enums used across API and event payloads."""

from enum import StrEnum


class FunctionType(StrEnum):
    TASK = "task"
    CRON = "cron"
    EVENT = "event"


class MissedRunPolicy(StrEnum):
    CATCH_UP = "catch_up"
    LATEST_ONLY = "latest_only"
    SKIP = "skip"


class DispatchReason(StrEnum):
    PAUSED = "paused"
    RATE_LIMITED = "rate_limited"
    NO_CAPACITY = "no_capacity"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


__all__ = [
    "FunctionType",
    "MissedRunPolicy",
    "DispatchReason",
]
