"""Queue constants shared by SDK and server components."""

# Redis key prefix used by the default queue implementation.
QUEUE_KEY_PREFIX = "upnext"

# Redis consumer group used by workers to claim jobs from streams.
QUEUE_CONSUMER_GROUP = "workers"

# Hash key namespace containing dispatch reason counters per function.
QUEUE_DISPATCH_REASONS_PREFIX = f"{QUEUE_KEY_PREFIX}:dispatch_reasons"

# Stream for sampled/structured dispatch reason events.
QUEUE_DISPATCH_EVENTS_STREAM = f"{QUEUE_KEY_PREFIX}:dispatch_events"
