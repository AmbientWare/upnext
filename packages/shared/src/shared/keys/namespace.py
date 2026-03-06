"""Workspace-scoped Redis namespace helpers."""

from __future__ import annotations

DEFAULT_WORKSPACE_ID = "local"
WORKSPACE_NAMESPACE_PREFIX = "upnext:workspaces"


def normalize_workspace_id(workspace_id: str | None) -> str:
    """Normalize workspace scope into a non-empty Redis-safe identifier."""
    normalized = (workspace_id or DEFAULT_WORKSPACE_ID).strip()
    if not normalized:
        return DEFAULT_WORKSPACE_ID
    return normalized


def workspace_namespace_prefix(workspace_id: str | None = None) -> str:
    """Build the root Redis key prefix for one workspace namespace."""
    return f"{WORKSPACE_NAMESPACE_PREFIX}:{normalize_workspace_id(workspace_id)}"


def scoped_key(*parts: str, workspace_id: str | None = None) -> str:
    """Build a Redis key under a workspace namespace."""
    return ":".join([workspace_namespace_prefix(workspace_id), *parts])
