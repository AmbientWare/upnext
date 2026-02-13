import logging
from collections.abc import Mapping
from datetime import datetime

from pydantic import ValidationError
from shared.contracts import ApiInstance, ApiRequestEvent, ApiRequestStreamEvent

from server.config import get_settings

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


def _normalize_stream_row(data: Mapping[str | bytes, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for raw_key, raw_value in data.items():
        if isinstance(raw_key, bytes):
            key = raw_key.decode()
        else:
            key = str(raw_key)

        if isinstance(raw_value, bytes):
            normalized[key] = raw_value.decode()
        else:
            normalized[key] = raw_value

    return normalized


def parse_api_request_event(
    event_id: str, data: Mapping[str | bytes, object]
) -> ApiRequestEvent | None:
    normalized = _normalize_stream_row(data)

    try:
        stream_event = ApiRequestStreamEvent.model_validate(normalized)
    except ValidationError:
        return None

    payload = stream_event.to_request_payload(event_id)
    method = payload.get("method")
    if isinstance(method, str):
        payload["method"] = method.upper()

    try:
        parsed = ApiRequestEvent.model_validate(payload)
    except ValidationError:
        return None

    if not parsed.api_name.strip():
        return None

    return parsed
