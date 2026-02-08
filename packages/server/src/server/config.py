from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    version: str = "0.0.1"

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
