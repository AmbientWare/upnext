"""API services layer."""

from server.services.api_instances import list_api_instances
from server.services.cleanup import CleanupService
from server.services.queue import get_queue_stats
from server.services.redis import close_redis, connect_redis, get_redis
from server.services.stream_subscriber import StreamSubscriber, StreamSubscriberConfig
from server.services.workers import (
    get_function_definitions,
    get_worker_definitions,
    get_worker_instance,
    get_worker_stats,
    list_worker_instances,
)

__all__ = [
    # Redis
    "connect_redis",
    "get_redis",
    "close_redis",
    # Stream subscriber
    "StreamSubscriber",
    "StreamSubscriberConfig",
    # Workers
    "get_worker_instance",
    "list_worker_instances",
    "get_worker_definitions",
    "get_worker_stats",
    "get_function_definitions",
    # API instances
    "list_api_instances",
    # Queue
    "get_queue_stats",
    # Cleanup
    "CleanupService",
]
