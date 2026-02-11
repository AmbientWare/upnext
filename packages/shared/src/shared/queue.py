"""Queue constants shared by SDK and server components."""

# Redis key prefix used by the default queue implementation.
QUEUE_KEY_PREFIX = "upnext"

# Redis consumer group used by workers to claim jobs from streams.
QUEUE_CONSUMER_GROUP = "workers"

