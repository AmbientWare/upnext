"""Backend for worker registration with Conduit server."""

from typing import Any

from conduit.engine.backend.api import ApiBackend, ApiBackendConfig, create_api_backend
from conduit.engine.backend.base import BaseBackend
from conduit.types import BackendType


async def create_backend(
    backend: BackendType,
    *,
    client: Any = None,
) -> BaseBackend | None:
    """
    Create the backend for worker registration.

    Args:
        backend: Backend type (ignored, always uses API backend)
        client: Unused, kept for backwards compatibility

    Returns:
        BaseBackend instance for worker registration
    """
    # Always use API backend for worker registration
    # Job events go through Redis streams (StatusPublisher -> server subscriber)
    return await create_api_backend()


__all__ = [
    "BaseBackend",
    "ApiBackend",
    "ApiBackendConfig",
    "create_api_backend",
    "create_backend",
    "BackendType",
]
