"""UpNext configuration with sensible defaults for development."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ThroughputMode(StrEnum):
    """Throughput mode for queue runtime profile."""

    THROUGHPUT = "throughput"
    SAFE = "safe"


class Settings(BaseSettings):
    """
    UpNext configuration.

    All settings can be overridden via environment variables with UPNEXT_ prefix.
    Defaults are set for local development - no configuration needed to get started.
    """

    model_config = SettingsConfigDict(
        env_prefix="UPNEXT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    debug: bool = False

    # UpNext server URL (for dashboard)
    url: str = "http://localhost:8000"

    # Redis URL for queue and persistence backend
    redis_url: str | None = None
    queue_runtime_profile: ThroughputMode = ThroughputMode.SAFE
    queue_job_ttl_seconds: int = 86_400
    queue_result_ttl_seconds: int = 3_600
    queue_claim_timeout_ms: int = 30_000
    queue_stream_maxlen: int = 0
    queue_dlq_stream_maxlen: int = 10_000
    queue_dispatch_events_stream_maxlen: int = 10_000
    queue_batch_size: int = 0
    queue_inbox_size: int = 0
    queue_outbox_size: int = 0
    queue_flush_interval_ms: float = 0.0
    worker_prefetch_default: int = 0

    # Status stream durability controls
    status_stream_max_len: int = 50_000
    status_publish_retry_attempts: int = 3
    status_publish_retry_base_ms: float = 25.0
    status_publish_retry_max_ms: float = 500.0
    status_pending_buffer_size: int = 10_000
    status_pending_flush_batch_size: int = 128
    status_durable_buffer_enabled: bool = True
    status_durable_buffer_key: str = "upnext:status:pending"
    status_durable_buffer_maxlen: int = 10_000
    status_shutdown_flush_timeout_seconds: float = 2.0
    status_publish_strict: bool = False

    # Progress coalescing controls
    progress_min_delta: float = 0.01
    progress_min_interval_seconds: float = 0.2

    # API tracking controls
    api_tracking_normalize_paths: bool = True
    api_tracking_registry_refresh_seconds: int = 60
    api_request_events_enabled: bool = True
    api_request_events_sample_rate: float = 1.0
    api_request_events_slow_ms: float = 500.0
    api_request_events_stream_max_len: int = 50_000

    # API key for authenticated access
    api_key: str | None = None

    # Environment mode
    env: str = "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.env in ("production", "prod")

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return not self.is_production

    def default_worker_prefetch(self, *, concurrency: int) -> int:
        """Resolve worker prefetch for current runtime profile."""
        if self.worker_prefetch_default > 0:
            return self.worker_prefetch_default
        if self.queue_runtime_profile == ThroughputMode.THROUGHPUT:
            return max(1, concurrency)
        return 1

    def default_queue_batch_size(self) -> int:
        """Resolve queue fetch/flush batch size for current runtime profile."""
        if self.queue_batch_size > 0:
            return self.queue_batch_size
        return 200 if self.queue_runtime_profile == ThroughputMode.THROUGHPUT else 100

    def default_queue_inbox_size(self, *, prefetch: int) -> int:
        """Resolve queue inbox capacity for current runtime profile."""
        if self.queue_inbox_size > 0:
            return max(prefetch, self.queue_inbox_size)
        return max(
            prefetch,
            2000 if self.queue_runtime_profile == ThroughputMode.THROUGHPUT else 1000,
        )

    def default_queue_outbox_size(self) -> int:
        """Resolve queue outbox capacity for current runtime profile."""
        if self.queue_outbox_size > 0:
            return self.queue_outbox_size
        return (
            20_000
            if self.queue_runtime_profile == ThroughputMode.THROUGHPUT
            else 10_000
        )

    def default_queue_flush_interval_seconds(self) -> float:
        """Resolve queue completion flush interval for current runtime profile."""
        if self.queue_flush_interval_ms > 0:
            return self.queue_flush_interval_ms / 1000
        return (
            0.02 if self.queue_runtime_profile == ThroughputMode.THROUGHPUT else 0.005
        )

    def default_queue_stream_maxlen(self) -> int:
        """Resolve queue stream retention cap for current runtime profile."""
        if self.queue_stream_maxlen > 0:
            return self.queue_stream_maxlen
        return 200_000 if self.queue_runtime_profile == ThroughputMode.THROUGHPUT else 0


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()
