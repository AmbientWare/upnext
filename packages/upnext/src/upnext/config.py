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
