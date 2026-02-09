import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import ValidationError
from shared.events import ARTIFACT_EVENTS_STREAM
from shared.schemas import (
    ArtifactStreamEvent,
)

from server.routes._shared import get_stream_json_object
from server.services import get_redis

logger = logging.getLogger(__name__)


def calculate_artifact_size(data: object) -> int | None:
    """Compute approximate payload size for inline text/json artifacts."""
    if data is None:
        return None
    if isinstance(data, str):
        return len(data.encode("utf-8"))
    if isinstance(data, (dict, list)):
        return len(json.dumps(data).encode("utf-8"))
    return None


def parse_artifact_stream_event(
    event_id: str, data: Mapping[str | bytes, object]
) -> ArtifactStreamEvent | None:
    payload = get_stream_json_object(data)
    if not payload:
        return None
    payload.setdefault("at", datetime.now(UTC).isoformat())
    try:
        return ArtifactStreamEvent.model_validate(payload)
    except ValidationError:
        logger.debug("Failed to parse artifact stream event id=%s", event_id)
        return None


async def publish_artifact_event(event: ArtifactStreamEvent) -> None:
    try:
        redis_client = await get_redis()
    except RuntimeError:
        return
    try:
        await redis_client.xadd(
            ARTIFACT_EVENTS_STREAM,
            {"data": event.model_dump_json()},
            maxlen=10_000,
            approximate=True,
        )
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Failed publishing artifact event: %s", exc)
