"""API tracking constants shared between SDK middleware and server reader.

Redis key structure:
    upnext:api:registry                                    -> SET of api names
    upnext:api:{api}:endpoints                             -> SET of "METHOD:path"
    upnext:api:{api}:{method}:{path}:m:{YYYY-MM-DDTHH:MM} -> HASH (minute bucket)
    upnext:api:{api}:{method}:{path}:h:{YYYY-MM-DDTHH}    -> HASH (hourly bucket)

Each hash contains:
    requests, errors, total_latency_ms, status_2xx, status_4xx, status_5xx
"""

# Key prefix for all API tracking keys
API_PREFIX = "upnext:apis"

# Key prefix for API instance heartbeats
API_INSTANCE_PREFIX = "upnext:apis:instances"

# TTLs (seconds)
MINUTE_BUCKET_TTL = 600  # 10 minutes
HOURLY_BUCKET_TTL = 2_592_000  # 30 days
REGISTRY_TTL = 2_592_000  # 30 days

# API instance TTL - must heartbeat within this time
# With 10s heartbeat interval, this gives 3 missed heartbeats before expiry
API_INSTANCE_TTL = 30


def api_registry_key() -> str:
    """Build API-name registry key."""
    return f"{API_PREFIX}:registry"


def api_endpoints_key(api_name: str) -> str:
    """Build per-API endpoint registry key."""
    return f"{API_PREFIX}:{api_name}:endpoints"


def api_minute_bucket_key(api_name: str, endpoint_key: str, minute_key: str) -> str:
    """Build minute metrics hash key for an API endpoint."""
    return f"{API_PREFIX}:{api_name}:{endpoint_key}:m:{minute_key}"


def api_hourly_bucket_key(api_name: str, endpoint_key: str, hour_key: str) -> str:
    """Build hourly metrics hash key for an API endpoint."""
    return f"{API_PREFIX}:{api_name}:{endpoint_key}:h:{hour_key}"


def api_instance_key(api_id: str) -> str:
    """Build API instance heartbeat key."""
    return f"{API_INSTANCE_PREFIX}:{api_id}"


def api_instance_pattern() -> str:
    """SCAN pattern for API instance heartbeat keys."""
    return f"{API_INSTANCE_PREFIX}:*"
