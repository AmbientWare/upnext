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

# TTLs (seconds)
MINUTE_BUCKET_TTL = 600  # 10 minutes
HOURLY_BUCKET_TTL = 2_592_000  # 30 days
REGISTRY_TTL = 2_592_000  # 30 days
