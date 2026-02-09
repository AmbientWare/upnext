from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from shared import __version__


class Settings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CONDUIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str | None = None
    database_url: str | None = None
    env: Literal["dev", "prod"] = "dev"
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    api_docs_url_template: str = "http://{host}:{port}/docs"
    api_realtime_enabled: bool = True
    api_request_events_default_limit: int = 200

    # Stream subscriber tuning (Redis consumer group worker).
    event_subscriber_batch_size: int = 100
    event_subscriber_poll_interval_ms: int = 2000
    event_subscriber_stale_claim_ms: int = 30000

    # Job progress write-throttling for DB persistence.
    event_progress_min_interval_ms: int = 250
    event_progress_min_delta: float = 0.02
    event_progress_force_interval_ms: int = 2000

    version: str = __version__

    @property
    def is_production(self) -> bool:
        return self.env == "prod"

    @property
    def is_development(self) -> bool:
        return self.env == "dev"

    @property
    def effective_database_url(self) -> str:
        """Get database URL, defaulting to SQLite if not configured."""
        if self.database_url:
            return self.database_url
        return "sqlite+aiosqlite:///conduit.db"

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite database."""
        return self.effective_database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
