"""Pattern matching utilities for event names.

This module provides wildcard pattern matching for event routing.
Both EventRouter and Registry use this shared implementation.
"""

from __future__ import annotations

import fnmatch


def matches_event_pattern(event: str, pattern: str) -> bool:
    """
    Check if an event name matches a pattern.

    Supports glob-style wildcards:
    - Exact match: "user.signup" matches "user.signup"
    - Single wildcard: "user.*" matches "user.signup" but not "user.signup.email"
    - Multi-wildcard: "user.**" matches "user.signup" and "user.signup.email"

    Args:
        event: Event name to check (e.g., "user.signup")
        pattern: Pattern to match against (e.g., "user.*")

    Returns:
        True if the event matches the pattern

    Examples:
        >>> matches_event_pattern("user.signup", "user.signup")
        True
        >>> matches_event_pattern("user.signup", "user.*")
        True
        >>> matches_event_pattern("user.signup.email", "user.*")
        False
        >>> matches_event_pattern("user.signup.email", "user.**")
        True
        >>> matches_event_pattern("order.item.added", "order.*.added")
        True
    """
    # Convert pattern to fnmatch-compatible format
    # "**" means match anything including dots
    # "*" means match anything except dots (single segment)

    if "**" in pattern:
        # Replace ** with a placeholder, then * with [^.]*, then restore **
        fnmatch_pattern = pattern.replace("**", "\x00")
        fnmatch_pattern = fnmatch_pattern.replace("*", "[^.]*")
        fnmatch_pattern = fnmatch_pattern.replace("\x00", "*")
    else:
        # Single * should not match dots
        fnmatch_pattern = pattern.replace("*", "[^.]*")

    return fnmatch.fnmatch(event, fnmatch_pattern)


def get_matching_patterns(event: str, patterns: list[str]) -> list[str]:
    """
    Find all patterns that match an event name.

    Args:
        event: Event name to match
        patterns: List of patterns to check

    Returns:
        List of matching patterns
    """
    return [p for p in patterns if matches_event_pattern(event, p)]
