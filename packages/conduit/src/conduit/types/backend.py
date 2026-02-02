"""Backend types."""

from enum import StrEnum


class BackendType(StrEnum):
    """Results backend type for job event persistence."""

    REDIS = "redis"
    API = "api"
