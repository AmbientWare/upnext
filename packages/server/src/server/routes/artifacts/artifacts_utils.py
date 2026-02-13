import base64
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from pydantic import ValidationError
from shared.artifacts import ArtifactType
from shared.contracts import ArtifactStreamEvent
from shared.keys import ARTIFACT_EVENTS_STREAM

from server.services.redis import get_redis
from server.shared_utils import get_stream_json_object

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


def infer_artifact_content_type(artifact_type: ArtifactType) -> str:
    if artifact_type == ArtifactType.TEXT:
        return "text/plain; charset=utf-8"
    if artifact_type == ArtifactType.JSON:
        return "application/json"
    if artifact_type == ArtifactType.PDF:
        return "application/pdf"
    if artifact_type == ArtifactType.CSV:
        return "text/csv"
    if artifact_type == ArtifactType.XML:
        return "application/xml"
    if artifact_type == ArtifactType.HTML:
        return "text/html"
    if artifact_type == ArtifactType.BINARY:
        return "application/octet-stream"
    if artifact_type == ArtifactType.SVG:
        return "image/svg+xml"
    # PNG/JPEG/WEBP/GIF already map directly.
    return artifact_type.value


def encode_artifact_payload(
    *,
    artifact_type: ArtifactType,
    data: Any,
) -> tuple[bytes, str]:
    """Encode request payload into bytes and return bytes + content type."""
    content_type = infer_artifact_content_type(artifact_type)

    if artifact_type == ArtifactType.TEXT:
        text = data if isinstance(data, str) else json.dumps(data)
        return text.encode("utf-8"), content_type

    if artifact_type == ArtifactType.JSON:
        if isinstance(data, str):
            return data.encode("utf-8"), content_type
        return json.dumps(data).encode("utf-8"), content_type

    # Image/file payloads are expected as base64-encoded strings.
    if not isinstance(data, str):
        raise ValueError(
            f"Artifact type '{artifact_type.value}' requires base64 string payload"
        )

    try:
        return base64.b64decode(data.encode("utf-8")), content_type
    except Exception as exc:
        raise ValueError("Failed to decode base64 artifact payload") from exc


def artifact_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


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
