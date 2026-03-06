"""Worker constants shared between SDK and server."""

from shared.keys.namespace import scoped_key

WORKER_INSTANCE_KEY_PREFIX = scoped_key("workers", "instances")
WORKER_DEF_PREFIX = scoped_key("workers", "definitions")
FUNCTION_KEY_PREFIX = scoped_key("functions")

# Worker heartbeat cadence (seconds)
WORKER_HEARTBEAT_INTERVAL = 5

# Worker instance TTL - must heartbeat within this time
# With 5s heartbeat interval, this gives 6 missed heartbeats before expiry
WORKER_TTL = 30

WORKER_EVENTS_STREAM = scoped_key("workers", "events")

# Worker/function definition TTL - refreshed each time a worker starts
# Matches API registry TTL so stale entries self-clean after 30 days
WORKER_DEF_TTL = 2_592_000  # 30 days
FUNCTION_DEF_TTL = 2_592_000  # 30 days


def worker_instance_key(worker_id: str, *, deployment_id: str | None = None) -> str:
    """Build worker-instance heartbeat key."""
    return scoped_key("workers", "instances", worker_id, deployment_id=deployment_id)


def worker_instance_pattern(*, deployment_id: str | None = None) -> str:
    """SCAN pattern for worker-instance heartbeat keys."""
    return scoped_key("workers", "instances", "*", deployment_id=deployment_id)


def worker_definition_key(
    worker_name: str,
    *,
    deployment_id: str | None = None,
) -> str:
    """Build worker definition key."""
    return scoped_key(
        "workers", "definitions", worker_name, deployment_id=deployment_id
    )


def worker_definition_pattern(*, deployment_id: str | None = None) -> str:
    """SCAN pattern for worker definition keys."""
    return scoped_key("workers", "definitions", "*", deployment_id=deployment_id)


def function_definition_key(
    function_key: str,
    *,
    deployment_id: str | None = None,
) -> str:
    """Build function definition key."""
    return scoped_key("functions", function_key, deployment_id=deployment_id)


def function_definition_pattern(*, deployment_id: str | None = None) -> str:
    """SCAN pattern for function definition keys."""
    return scoped_key("functions", "*", deployment_id=deployment_id)


def worker_events_stream_key(*, deployment_id: str | None = None) -> str:
    """Build worker heartbeat/lifecycle signal stream key."""
    return scoped_key("workers", "events", deployment_id=deployment_id)
