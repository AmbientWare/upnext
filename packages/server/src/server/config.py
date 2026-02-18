import logging
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from shared._version import __version__

logger = logging.getLogger(__name__)

_UPNEXT_HOME = Path.home() / ".upnext"
_SECRET_KEY_FILE = _UPNEXT_HOME / "secret_key"
_SECRET_KEY_FILE_MODE = 0o600


def _get_or_create_secret_key() -> str:
    """Read a persisted Fernet key from disk, or generate and save one."""
    if _SECRET_KEY_FILE.exists():
        try:
            _SECRET_KEY_FILE.chmod(_SECRET_KEY_FILE_MODE)
        except OSError:
            logger.debug("Could not tighten secret key file permissions")
        return _SECRET_KEY_FILE.read_text().strip()

    _SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode()
    _SECRET_KEY_FILE.write_text(key)
    try:
        _SECRET_KEY_FILE.chmod(_SECRET_KEY_FILE_MODE)
    except OSError:
        logger.debug("Could not set secret key file permissions")
    logger.info("Generated new secret key at %s", _SECRET_KEY_FILE)
    logger.warning(
        "For production, set UPNEXT_SECRET_KEY to a secure random string. Fernet compatible."
    )

    return key


class Environments(StrEnum):
    DEV = "dev"
    PROD = "prod"

    def is_production(self) -> bool:
        return self == self.PROD

    def is_development(self) -> bool:
        return self == self.DEV


class Settings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="UPNEXT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str | None = None
    database_url: str | None = None
    env: Environments = Environments.DEV
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    log_format: Literal["text", "json"] = "text"
    api_docs_url_template: str = "http://{host}:{port}/docs"
    api_request_events_default_limit: int = 200
    cors_allow_origins: str = "*"
    cors_allow_credentials: bool = False
    readiness_require_redis: bool = False

    # Authentication
    auth_enabled: bool = False
    api_key: str | None = None
    secrets_require_admin_reads: bool = False

    # Encryption key for secrets storage.
    # Auto-generated and persisted to ~/.upnext/secret_key if not set via env.
    secret_key: str = ""

    # Artifact storage
    artifact_max_upload_bytes: int = 256 * 1024 * 1024  # 256 MB
    artifact_storage_backend: Literal["local", "s3"] = "local"
    artifact_storage_local_root: str = str(_UPNEXT_HOME / "artifacts")
    artifact_storage_s3_bucket: str | None = None
    artifact_storage_s3_prefix: str = "upnext/artifacts"
    artifact_storage_s3_region: str | None = None
    artifact_storage_s3_endpoint_url: str | None = None

    # Stream subscriber tuning (Redis consumer group worker).
    event_subscriber_batch_size: int = 100
    event_subscriber_poll_interval_ms: int = 2000
    event_subscriber_stale_claim_ms: int = 30000
    event_subscriber_invalid_stream: str = "upnext:status:events:invalid"
    event_subscriber_invalid_stream_maxlen: int = 10_000

    # Cleanup service tuning.
    cleanup_retention_days: int = 30
    cleanup_interval_hours: int = 1
    cleanup_pending_retention_hours: int = 24
    cleanup_pending_promote_batch: int = 500
    cleanup_pending_promote_max_loops: int = 20
    cleanup_startup_jitter_seconds: float = 30.0

    # Queue retention defaults (also used by server-side cancel/retry endpoints).
    queue_job_ttl_seconds: int = 86_400
    queue_result_ttl_seconds: int = 3_600
    queue_stream_maxlen: int = 0
    queue_dlq_stream_maxlen: int = 10_000
    queue_dispatch_events_stream_maxlen: int = 10_000

    # Job progress write-throttling for DB persistence.
    event_progress_min_interval_ms: int = 250
    event_progress_min_delta: float = 0.02
    event_progress_force_interval_ms: int = 2000
    event_progress_state_max_entries: int = 10000

    # Operational alert hook settings.
    alert_webhook_url: str | None = None
    alert_webhook_timeout_seconds: float = 3.0
    alert_cooldown_seconds: int = 300
    alert_failure_min_runs_24h: int = 10
    alert_failure_rate_threshold: float = 20.0
    alert_p95_duration_ms_threshold: float = 30_000.0
    alert_p95_wait_ms_threshold: float = 10_000.0
    alert_queue_backlog_threshold: int = 100
    alert_invalid_event_rate_threshold: int = 50
    alert_poll_interval_seconds: float = 60.0

    # Runbook dashboard panel settings.
    dashboard_top_failing_limit: int = 5
    dashboard_oldest_queued_limit: int = 10
    dashboard_stuck_active_limit: int = 10
    dashboard_stuck_active_seconds: int = 900

    version: str = __version__

    @field_validator("env", mode="before")
    @classmethod
    def _normalize_env_aliases(cls, value: object) -> object:
        """Allow long-form env aliases for compatibility with docs/SDK defaults."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            aliases = {
                "development": Environments.DEV.value,
                "production": Environments.PROD.value,
            }
            return aliases.get(normalized, normalized)
        return value

    @property
    def is_production(self) -> bool:
        return self.env.is_production()

    @property
    def is_development(self) -> bool:
        return self.env.is_development()

    @property
    def effective_database_url(self) -> str:
        """Get database URL, defaulting to SQLite if not configured."""
        if self.database_url:
            return self.database_url
        return "sqlite+aiosqlite:///upnext.db"

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite database."""
        return self.effective_database_url.startswith("sqlite")

    @property
    def cors_allow_origins_list(self) -> list[str]:
        """Parse comma-delimited CORS origins into a list."""
        origins = [origin.strip() for origin in self.cors_allow_origins.split(",")]
        cleaned = [origin for origin in origins if origin]
        return cleaned or ["*"]

    @property
    def effective_secrets_require_admin_reads(self) -> bool:
        """Resolve secret read policy from explicit configuration."""
        return self.secrets_require_admin_reads

    def model_post_init(self, __context: object) -> None:
        if not self.secret_key:
            self.secret_key = _get_or_create_secret_key()


@lru_cache
def get_settings() -> Settings:
    return Settings()
