from collections.abc import Mapping

from pydantic import ValidationError
from shared.contracts import WorkerSignalStreamEvent

from server.shared_utils import get_stream_json_object, get_stream_text_field

STREAMABLE_WORKER_EVENTS = frozenset(
    {
        "worker.heartbeat",
        "worker.definition.updated",
        "worker.stopped",
    }
)


def parse_worker_signal_type(data: Mapping[str | bytes, object]) -> str | None:
    payload = get_stream_json_object(data)
    if payload is not None:
        try:
            return WorkerSignalStreamEvent.model_validate(payload).type
        except ValidationError:
            return None

    signal_type = get_stream_text_field(data, "type")
    if not signal_type:
        return None
    try:
        return WorkerSignalStreamEvent.model_validate({"type": signal_type}).type
    except ValidationError:
        return None
