"""API instances service - reads API instance heartbeats from Redis.

API instances write their own heartbeat data directly to Redis (via the SDK).
This module reads those keys for the dashboard.
"""

import json
import logging

from shared.api import API_INSTANCE_PREFIX
from shared.schemas import ApiInstance

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


async def list_api_instances() -> list[ApiInstance]:
    """List all active API instances from Redis."""
    r = await get_redis()
    instances: list[ApiInstance] = []

    async for key in r.scan_iter(match=f"{API_INSTANCE_PREFIX}:*", count=100):
        data = await r.get(key)
        if data:
            d = json.loads(data)
            instances.append(
                ApiInstance(
                    id=d["id"],
                    api_name=d["api_name"],
                    started_at=d["started_at"],
                    last_heartbeat=d["last_heartbeat"],
                    host=d.get("host", "0.0.0.0"),
                    port=d.get("port", 8000),
                    endpoints=d.get("endpoints", []),
                    hostname=d.get("hostname"),
                )
            )

    return instances
