"""Pattern matching utilities for event names.

This module provides wildcard pattern matching for event routing.
Both EventRouter and Registry use this shared implementation.
"""

from __future__ import annotations

import re


def _segment_regex(pattern: str) -> str:
    """Compile one dot-delimited segment pattern into a regex fragment."""
    out: list[str] = []
    for char in pattern:
        if char == "*":
            # Single-segment wildcard: any chars except dot.
            out.append("[^.]+")
        else:
            out.append(re.escape(char))
    return "".join(out)


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
    if pattern == "**":
        return True

    event_parts = event.split(".")
    pattern_parts = pattern.split(".")

    i = 0
    j = 0
    while i < len(pattern_parts) and j < len(event_parts):
        segment = pattern_parts[i]
        if segment == "**":
            # Multi-segment wildcard: consume any remaining segments.
            return True
        if not re.fullmatch(_segment_regex(segment), event_parts[j]):
            return False
        i += 1
        j += 1

    if i == len(pattern_parts) and j == len(event_parts):
        return True
    if i == len(pattern_parts) - 1 and pattern_parts[i] == "**":
        return True
    return False


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
