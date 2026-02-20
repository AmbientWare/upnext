"""Queue constants and Redis key helpers shared by SDK and server components."""

# Redis key prefix used by the default queue implementation.
QUEUE_KEY_PREFIX = "upnext"

# Redis consumer group used by workers to claim jobs from streams.
QUEUE_CONSUMER_GROUP = "workers"

# Hash key namespace containing dispatch reason counters per function.
QUEUE_DISPATCH_REASONS_PREFIX = f"{QUEUE_KEY_PREFIX}:dispatch_reasons"


def queue_key(*parts: str, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Build a queue Redis key under the configured prefix."""
    return ":".join([key_prefix, *parts])


def function_stream_key(function: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis stream key for immediate jobs of a function."""
    return queue_key("fn", function, "stream", key_prefix=key_prefix)


def function_stream_pattern(*, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """SCAN pattern for all function stream keys."""
    return queue_key("fn", "*", "stream", key_prefix=key_prefix)


def function_scheduled_key(
    function: str,
    *,
    key_prefix: str = QUEUE_KEY_PREFIX,
) -> str:
    """Redis sorted-set key for scheduled jobs of a function."""
    return queue_key("fn", function, "scheduled", key_prefix=key_prefix)


def function_scheduled_pattern(*, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """SCAN pattern for all function scheduled sorted-set keys."""
    return queue_key("fn", "*", "scheduled", key_prefix=key_prefix)


def function_dedup_key(function: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis set key for active idempotency keys of a function."""
    return queue_key("fn", function, "dedup", key_prefix=key_prefix)


def function_dlq_stream_key(
    function: str,
    *,
    key_prefix: str = QUEUE_KEY_PREFIX,
) -> str:
    """Redis stream key for dead-letter jobs of a function."""
    return queue_key("fn", function, "dlq", key_prefix=key_prefix)


def function_dlq_stream_pattern(*, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """SCAN pattern for all function dead-letter stream keys."""
    return queue_key("fn", "*", "dlq", key_prefix=key_prefix)


def function_rate_limit_key(
    function: str,
    *,
    key_prefix: str = QUEUE_KEY_PREFIX,
) -> str:
    """Redis key tracking a function's queue-side rate-limit state."""
    return queue_key("fn", function, "rate_limit", key_prefix=key_prefix)


def dispatch_reasons_key(
    function: str,
    *,
    key_prefix: str = QUEUE_KEY_PREFIX,
) -> str:
    """Redis hash key for queue dispatch reason counters of a function."""
    return queue_key("dispatch_reasons", function, key_prefix=key_prefix)


def dispatch_reasons_prefix(*, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis key prefix for queue dispatch reason hashes."""
    return queue_key("dispatch_reasons", key_prefix=key_prefix)


def dispatch_reasons_pattern(*, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """SCAN pattern for dispatch reason hashes."""
    return queue_key("dispatch_reasons", "*", key_prefix=key_prefix)


def dispatch_events_stream_key(*, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis stream key for queue dispatch events."""
    return queue_key("dispatch_events", key_prefix=key_prefix)


def job_key(function: str, job_id: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis key storing serialized Job payload."""
    return queue_key("job", function, job_id, key_prefix=key_prefix)


def job_match_pattern(job_id: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """SCAN pattern for a job ID across all function namespaces."""
    return queue_key("job", "*", job_id, key_prefix=key_prefix)


def job_index_key(job_id: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis key mapping job ID to canonical job storage key."""
    return queue_key("job_index", job_id, key_prefix=key_prefix)


def job_result_key(job_id: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis key storing a terminal job result snapshot."""
    return queue_key("result", job_id, key_prefix=key_prefix)


def job_cancelled_key(job_id: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Redis key used as pre-execution cancellation marker."""
    return queue_key("cancelled", job_id, key_prefix=key_prefix)


def job_status_channel(job_id: str, *, key_prefix: str = QUEUE_KEY_PREFIX) -> str:
    """Pub/Sub channel for job status updates."""
    return queue_key("job", job_id, key_prefix=key_prefix)


def cron_registry_member_key(function: str) -> str:
    """Canonical cron registry member key for a function."""
    return f"cron:{function}"


def cron_window_job_key(function: str, window_token: str) -> str:
    """Canonical per-window cron job dedupe key."""
    return f"{cron_registry_member_key(function)}:{window_token}"
