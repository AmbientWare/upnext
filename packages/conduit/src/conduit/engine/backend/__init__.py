"""Job event backends for reporting to different targets."""

import logging
from typing import Any

import redis.asyncio

from conduit.config import get_settings
from conduit.engine.backend.api import ApiBackend, ApiBackendConfig, create_api_backend
from conduit.engine.backend.base import BaseBackend
from conduit.engine.backend.redis import RedisBackend
from conduit.types import BackendType

logger = logging.getLogger(__name__)


async def create_backend(
    backend: BackendType,
    *,
    client: Any = None,
) -> BaseBackend | None:
    """
    Create the appropriate backend based on backend type.

    Args:
        backend: Backend type to use.
        client: Pre-existing Redis client. If provided, used directly
                for REDIS backend instead of creating one from settings.

    Returns:
        BaseBackend instance
    """
    if backend == BackendType.REDIS:
        if client is None:
            settings = get_settings()
            if not settings.redis_url:
                logger.debug("BackendType.REDIS requested but no redis_url configured")
                return None
            client = redis.asyncio.from_url(settings.redis_url)
        return RedisBackend(client)

    else:
        return await create_api_backend()


__all__ = [
    "BaseBackend",
    "ApiBackend",
    "ApiBackendConfig",
    "create_api_backend",
    "create_backend",
    "BackendType",
]
