"""Worker constants shared between SDK and server."""

# Key prefix for worker instance heartbeats
WORKER_INSTANCE_KEY_PREFIX = "conduit:workers:instances"

# Key prefix for persistent worker definitions (keyed by worker name)
WORKER_DEF_PREFIX = "conduit:workers:definitions"

# Key prefix for function definitions
FUNCTION_KEY_PREFIX = "conduit:functions"

# Worker instance TTL - must heartbeat within this time
# With 10s heartbeat interval, this gives 3 missed heartbeats before expiry
WORKER_TTL = 30

# Stream used for worker heartbeat/lifecycle signals consumed by realtime routes
WORKER_EVENTS_STREAM = "conduit:workers:events"

# Worker/function definition TTL - refreshed each time a worker starts
# Matches API registry TTL so stale entries self-clean after 30 days
WORKER_DEF_TTL = 2_592_000  # 30 days
FUNCTION_DEF_TTL = 2_592_000  # 30 days
