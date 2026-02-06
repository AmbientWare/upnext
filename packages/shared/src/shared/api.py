"""API tracking constants shared between SDK middleware and server reader.

Redis key structure:
    conduit:api:registry                                    -> SET of api names
    conduit:api:{api}:endpoints                             -> SET of "METHOD:path"
    conduit:api:{api}:{method}:{path}:m:{YYYY-MM-DDTHH:MM} -> HASH (minute bucket)
    conduit:api:{api}:{method}:{path}:h:{YYYY-MM-DDTHH}    -> HASH (hourly bucket)

Each hash contains:
    requests, errors, total_latency_ms, status_2xx, status_4xx, status_5xx
"""

# Key prefix for all API tracking keys
API_PREFIX = "conduit:api"

# Key prefix for API instance heartbeats
API_INSTANCE_PREFIX = "conduit:api_instances"

# TTLs (seconds)
MINUTE_BUCKET_TTL = 600  # 10 minutes
HOURLY_BUCKET_TTL = 2_592_000  # 30 days
REGISTRY_TTL = 2_592_000  # 30 days

# API instance TTL - must heartbeat within this time
# With 10s heartbeat interval, this gives 3 missed heartbeats before expiry
API_INSTANCE_TTL = 30
