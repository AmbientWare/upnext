from collections.abc import Mapping

from server.routes._shared import get_stream_json_object, get_stream_text_field

WORKER_SIGNAL_TYPES = frozenset(
    {
        "worker.heartbeat",
        "worker.definition.updated",
        "worker.stopped",
    }
)


def parse_worker_signal_type(data: Mapping[str | bytes, object]) -> str | None:
    payload = get_stream_json_object(data)
    if payload:
        signal_type = payload.get("type")
        if isinstance(signal_type, str) and signal_type:
            return signal_type

    return get_stream_text_field(data, "type")
