"""API tracking constants shared between SDK middleware and server reader.

Redis key structure:
    upnext:api:registry                                    -> SET of api names
    upnext:api:{api}:endpoints                             -> SET of "METHOD:path"
    upnext:api:{api}:{method}:{path}:m:{YYYY-MM-DDTHH:MM} -> HASH (minute bucket)
    upnext:api:{api}:{method}:{path}:h:{YYYY-MM-DDTHH}    -> HASH (hourly bucket)

Each hash contains:
    requests, errors, total_latency_ms, status_2xx, status_4xx, status_5xx
"""

from shared.keys.namespace import scoped_key

API_PREFIX = scoped_key("apis")
API_INSTANCE_PREFIX = scoped_key("apis", "instances")

# TTLs (seconds)
# Keep enough minute resolution to support up to 1h dashboard windows.
MINUTE_BUCKET_TTL = 7_200  # 2 hours
HOURLY_BUCKET_TTL = 2_592_000  # 30 days
REGISTRY_TTL = 2_592_000  # 30 days

# API instance TTL - must heartbeat within this time
# With 10s heartbeat interval, this gives 3 missed heartbeats before expiry
API_INSTANCE_TTL = 30


def api_registry_key(*, workspace_id: str | None = None) -> str:
    """Build API-name registry key."""
    return scoped_key("apis", "registry", workspace_id=workspace_id)


def api_endpoints_key(api_name: str, *, workspace_id: str | None = None) -> str:
    """Build per-API endpoint registry key."""
    return scoped_key("apis", api_name, "endpoints", workspace_id=workspace_id)


def api_minute_bucket_key(
    api_name: str,
    endpoint_key: str,
    minute_key: str,
    *,
    workspace_id: str | None = None,
) -> str:
    """Build minute metrics hash key for an API endpoint."""
    return scoped_key(
        "apis",
        api_name,
        endpoint_key,
        "m",
        minute_key,
        workspace_id=workspace_id,
    )


def api_hourly_bucket_key(
    api_name: str,
    endpoint_key: str,
    hour_key: str,
    *,
    workspace_id: str | None = None,
) -> str:
    """Build hourly metrics hash key for an API endpoint."""
    return scoped_key(
        "apis",
        api_name,
        endpoint_key,
        "h",
        hour_key,
        workspace_id=workspace_id,
    )


def api_instance_key(api_id: str, *, workspace_id: str | None = None) -> str:
    """Build API instance heartbeat key."""
    return scoped_key("apis", "instances", api_id, workspace_id=workspace_id)


def api_instance_pattern(*, workspace_id: str | None = None) -> str:
    """SCAN pattern for API instance heartbeat keys."""
    return scoped_key("apis", "instances", "*", workspace_id=workspace_id)
