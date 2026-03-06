"""API instances service - reads API instance heartbeats from Redis.

API instances write their own heartbeat data directly to Redis (via the SDK).
This module reads those keys for the dashboard.
"""

import json
import logging

from shared.contracts import ApiInstance
from shared.keys import DEFAULT_DEPLOYMENT_ID, api_instance_pattern

from server.services.redis import get_redis

logger = logging.getLogger(__name__)


async def list_api_instances(
    *, deployment_id: str = DEFAULT_DEPLOYMENT_ID
) -> list[ApiInstance]:
    """List all active API instances from Redis."""
    r = await get_redis()
    instances: list[ApiInstance] = []

    async for key in r.scan_iter(
        match=api_instance_pattern(deployment_id=deployment_id),
        count=100,
    ):
        data = await r.get(key)
        if data:
            d = json.loads(data)
            instances.append(ApiInstance.model_validate(d))

    return instances
