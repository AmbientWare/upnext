"""UpNext configuration with sensible defaults for development."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    queue_job_ttl_seconds: int = 86_400
    queue_result_ttl_seconds: int = 3_600
    queue_claim_timeout_ms: int = 30_000
    queue_dlq_stream_maxlen: int = 10_000
    queue_dispatch_events_stream_maxlen: int = 10_000

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
    status_durable_probe_interval_seconds: float = 2.0
    status_durable_flush_interval_seconds: float = 0.25
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


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()
