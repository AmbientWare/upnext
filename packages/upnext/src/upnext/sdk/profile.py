"""Worker queue profile for UpNext."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkerProfile:
    """Queue tuning profile for a Worker.

    Use the built-in presets via ``ProfileOptions``, or create a custom profile
    for fine-grained control.

    Example:
        import upnext

        # Built-in presets
        worker = upnext.Worker("my-worker", profile=upnext.ProfileOptions.THROUGHPUT)

        # Custom profile
        worker = upnext.Worker(
            "my-worker",
            profile=upnext.WorkerProfile(batch_size=500, inbox_size=5000),
        )
    """

    batch_size: int = 100
    inbox_size: int = 1000
    outbox_size: int = 10_000
    flush_interval_ms: float = 5.0
    claim_timeout_ms: int = 30_000
    job_ttl_seconds: int = 86_400
    result_ttl_seconds: int = 3_600
    stream_maxlen: int = 0
    dlq_stream_maxlen: int = 10_000

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if self.stream_maxlen < 0:
            raise ValueError("stream_maxlen must be >= 0")
        if self.flush_interval_ms <= 0:
            raise ValueError("flush_interval_ms must be > 0")


@dataclass
class ThroughputProfile(WorkerProfile):
    """Aggressive settings optimized for maximum throughput."""

    batch_size: int = 200
    inbox_size: int = 2000
    outbox_size: int = 20_000
    flush_interval_ms: float = 20.0
    stream_maxlen: int = 200_000


@dataclass
class SafeProfile(WorkerProfile):
    """Conservative settings optimized for reliability."""

    batch_size: int = 100
    inbox_size: int = 1000
    outbox_size: int = 10_000


class ProfileOptions:
    """Built-in profile presets for a Worker."""

    SAFE: WorkerProfile = SafeProfile()
    THROUGHPUT: WorkerProfile = ThroughputProfile()
