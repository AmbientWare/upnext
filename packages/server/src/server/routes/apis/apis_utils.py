import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from shared.schemas import ApiInstance, ApiRequestEvent

from server.config import get_settings
from server.routes._shared import get_stream_json_object, get_stream_text_field

logger = logging.getLogger(__name__)


def normalize_docs_host(host: str) -> str:
    if host in {"0.0.0.0", "::", ""}:
        return "localhost"
    return host


def build_docs_url(api_name: str, instances: list[ApiInstance]) -> str | None:
    if not instances:
        return None

    try:
        primary = max(
            instances,
            key=lambda item: datetime.fromisoformat(
                item.last_heartbeat.replace("Z", "+00:00")
            ),
        )
    except Exception:
        primary = instances[0]

    settings = get_settings()
    template = settings.api_docs_url_template
    try:
        return template.format(
            api_name=api_name,
            host=normalize_docs_host(primary.host),
            port=primary.port,
        )
    except Exception:
        logger.exception("Failed to format docs URL for api_name=%s", api_name)
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def parse_api_request_event(
    event_id: str, data: Mapping[str | bytes, object]
) -> ApiRequestEvent | None:
    payload = get_stream_json_object(data) or {}

    at = payload.get("at")
    if not isinstance(at, str) or not at:
        at = get_stream_text_field(data, "at") or datetime.now(UTC).isoformat()

    api_name = payload.get("api_name")
    if not isinstance(api_name, str) or not api_name.strip():
        api_name = get_stream_text_field(data, "api_name") or ""
    if not api_name.strip():
        return None

    method = payload.get("method")
    if not isinstance(method, str) or not method:
        method = get_stream_text_field(data, "method") or "GET"
    method = method.upper()

    path = payload.get("path")
    if not isinstance(path, str) or not path:
        path = get_stream_text_field(data, "path") or "/"

    status_raw = payload.get("status", get_stream_text_field(data, "status"))
    status = _coerce_int(status_raw)
    if status is None:
        return None

    latency_raw = payload.get("latency_ms", get_stream_text_field(data, "latency_ms"))
    latency_ms = _coerce_float(latency_raw)
    if latency_ms is None:
        return None

    instance_id = payload.get("instance_id")
    if instance_id is None:
        instance_id = get_stream_text_field(data, "instance_id")
    elif not isinstance(instance_id, str):
        instance_id = str(instance_id)

    sampled = _coerce_bool(
        payload.get("sampled"),
        _coerce_bool(get_stream_text_field(data, "sampled"), False),
    )

    normalized_payload = {
        "id": str(payload.get("id") or event_id),
        "at": at,
        "api_name": api_name,
        "method": method,
        "path": path,
        "status": status,
        "latency_ms": latency_ms,
        "instance_id": instance_id,
        "sampled": sampled,
    }

    try:
        return ApiRequestEvent.model_validate(normalized_payload)
    except ValidationError:
        return None
