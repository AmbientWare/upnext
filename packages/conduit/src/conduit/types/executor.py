"""Executor types."""

from enum import StrEnum


class SyncExecutor(StrEnum):
    """Executor type for sync task functions."""

    THREAD = "thread"
    PROCESS = "process"
