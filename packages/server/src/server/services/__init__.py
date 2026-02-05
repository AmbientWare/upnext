"""API services layer."""

from server.services.queue import get_queue_stats
from server.services.redis import close_redis, connect_redis, get_redis
from server.services.stream_subscriber import StreamSubscriber, StreamSubscriberConfig
from server.services.workers import (
    deregister_worker,
    get_function_definitions,
    get_worker,
    get_worker_stats,
    heartbeat_worker,
    list_workers,
    register_worker,
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
    "register_worker",
    "deregister_worker",
    "heartbeat_worker",
    "get_worker",
    "list_workers",
    "get_worker_stats",
    "get_function_definitions",
    # Queue
    "get_queue_stats",
]
