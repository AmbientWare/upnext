"""Worker constants shared between SDK and server."""

# Key prefix for worker instance heartbeats
WORKER_INSTANCE_KEY_PREFIX = "upnext:workers:instances"

# Key prefix for persistent worker definitions (keyed by worker name)
WORKER_DEF_PREFIX = "upnext:workers:definitions"

# Key prefix for function definitions
FUNCTION_KEY_PREFIX = "upnext:functions"

# Worker heartbeat cadence (seconds)
WORKER_HEARTBEAT_INTERVAL = 5

# Worker instance TTL - must heartbeat within this time
# With 5s heartbeat interval, this gives 6 missed heartbeats before expiry
WORKER_TTL = 30

# Stream used for worker heartbeat/lifecycle signals consumed by realtime routes
WORKER_EVENTS_STREAM = "upnext:workers:events"

# Worker/function definition TTL - refreshed each time a worker starts
# Matches API registry TTL so stale entries self-clean after 30 days
WORKER_DEF_TTL = 2_592_000  # 30 days
FUNCTION_DEF_TTL = 2_592_000  # 30 days
