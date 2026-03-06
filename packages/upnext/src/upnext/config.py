"""UpNext configuration with sensible defaults for development."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from shared.keys import (
    DEFAULT_WORKSPACE_ID,
    workspace_namespace_prefix,
    normalize_workspace_id,
    status_events_stream_key,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeModes(StrEnum):
    SELF_HOSTED = "self_hosted"
    CLOUD_RUNTIME = "cloud_runtime"


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

    cloud_url: str = "https://upnext.run"

    debug: bool = False

    # UpNext server URL (for dashboard)
    url: str = "http://localhost:8000"

    # Redis URL for queue and persistence backend
    redis_url: str | None = None
    workspace_id: str = DEFAULT_WORKSPACE_ID
    runtime_mode: RuntimeModes = RuntimeModes.SELF_HOSTED
    queue_batch_size: int = 4
    queue_inbox_size: int = 4
    queue_outbox_size: int = 10_000
    queue_flush_interval_ms: float = 5.0
    queue_job_ttl_seconds: int = 86_400
    queue_claim_timeout_ms: int = 30_000
    queue_stream_maxlen: int = 0
    queue_dispatch_events_stream_maxlen: int = 10_000

    # Status stream durability controls
    status_stream_max_len: int = 50_000
    status_publish_retry_attempts: int = 3
    status_publish_retry_base_ms: float = 25.0
    status_publish_retry_max_ms: float = 500.0
    status_pending_buffer_size: int = 10_000
    status_pending_flush_batch_size: int = 128
    status_durable_buffer_enabled: bool = True
    status_durable_buffer_key: str | None = None
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

    @property
    def is_cloud_runtime(self) -> bool:
        return self.runtime_mode == RuntimeModes.CLOUD_RUNTIME

    @property
    def normalized_workspace_id(self) -> str:
        """Workspace identifier for all Redis-backed runtime state."""
        return normalize_workspace_id(self.workspace_id)

    @property
    def runtime_key_prefix(self) -> str:
        """Redis key prefix for this runtime workspace namespace."""
        return workspace_namespace_prefix(self.normalized_workspace_id)

    @property
    def status_events_stream(self) -> str:
        """Redis stream key for job lifecycle events."""
        return status_events_stream_key(workspace_id=self.normalized_workspace_id)

    @property
    def effective_status_durable_buffer_key(self) -> str:
        """Resolve the durable pending buffer key inside the workspace namespace."""
        if self.status_durable_buffer_key:
            return self.status_durable_buffer_key
        return f"{self.runtime_key_prefix}:status:pending"

    def model_post_init(self, __context: object) -> None:
        if (
            self.is_cloud_runtime
            and self.normalized_workspace_id == DEFAULT_WORKSPACE_ID
        ):
            raise ValueError(
                "UPNEXT_WORKSPACE_ID must be set to a non-local value when "
                "UPNEXT_RUNTIME_MODE=cloud_runtime"
            )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()
