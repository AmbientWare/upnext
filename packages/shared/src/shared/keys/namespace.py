"""Deployment-scoped Redis namespace helpers."""

from __future__ import annotations

DEFAULT_DEPLOYMENT_ID = "local"
DEPLOYMENT_NAMESPACE_PREFIX = "upnext:deployments"


def normalize_deployment_id(deployment_id: str | None) -> str:
    """Normalize deployment scope into a non-empty Redis-safe identifier."""
    normalized = (deployment_id or DEFAULT_DEPLOYMENT_ID).strip()
    if not normalized:
        return DEFAULT_DEPLOYMENT_ID
    return normalized


def deployment_namespace_prefix(deployment_id: str | None = None) -> str:
    """Build the root Redis key prefix for one deployment namespace."""
    return f"{DEPLOYMENT_NAMESPACE_PREFIX}:{normalize_deployment_id(deployment_id)}"


def scoped_key(*parts: str, deployment_id: str | None = None) -> str:
    """Build a Redis key under a deployment namespace."""
    return ":".join([deployment_namespace_prefix(deployment_id), *parts])
