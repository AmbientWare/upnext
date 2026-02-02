"""Conduit configuration with sensible defaults for development."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Conduit configuration.

    All settings can be overridden via environment variables with CONDUIT_ prefix.
    Defaults are set for local development - no configuration needed to get started.
    """

    model_config = SettingsConfigDict(
        env_prefix="CONDUIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API server URL (for job tracking/dashboard, used when backend="api")
    # Default to localhost for dev, override with CONDUIT_URL for cloud
    url: str = "http://localhost:8000"

    # Redis URL for queue and persistence backend
    redis_url: str | None = None

    # API key for authenticated access (required for backend="api" in production)
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
