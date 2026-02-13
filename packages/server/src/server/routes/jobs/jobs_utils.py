from collections.abc import Mapping

from shared.contracts import JobHistoryResponse

from server.db.tables import JobHistory
from server.shared_utils import get_stream_json_object

STREAMABLE_EVENTS = frozenset(
    {
        "job.started",
        "job.completed",
        "job.failed",
        "job.retrying",
    }
)


def extract_stream_function_key(data: Mapping[str | bytes, object]) -> str | None:
    parsed = get_stream_json_object(data)
    if not parsed:
        return None
    function = parsed.get("function")
    return str(function) if function else None


def job_history_to_response(job: JobHistory) -> JobHistoryResponse:
    """Convert a JobHistory row into API response shape."""
    return JobHistoryResponse.model_validate(job)
