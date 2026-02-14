"""Structured logging configuration."""

import json
import logging
from datetime import UTC, datetime

from server.middleware import CorrelationIDFilter


class JSONFormatter(logging.Formatter):
    """JSON log formatter compatible with ECS/Splunk/Datadog structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["error"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "stacktrace": self.formatException(record.exc_info),
            }
        cid = getattr(record, "correlation_id", None)
        if cid is not None:
            log_entry["correlation_id"] = cid
        return json.dumps(log_entry, default=str)


def configure_logging(*, log_format: str = "text", debug: bool = False) -> None:
    """Configure root logger with the specified format."""
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates.
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setLevel(level)

    # Attach the correlation ID filter so every record carries the request ID.
    handler.addFilter(CorrelationIDFilter())

    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    root.addHandler(handler)
