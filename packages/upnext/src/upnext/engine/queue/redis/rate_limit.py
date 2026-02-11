from __future__ import annotations

import re
from dataclasses import dataclass

_RATE_LIMIT_PATTERN = re.compile(r"^\s*(\d+)\s*/\s*(?:(\d+)\s*)?([smhd])\s*$")
_UNIT_SECONDS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


@dataclass(frozen=True)
class RateLimit:
    """Parsed rate limit definition."""

    capacity: int
    window_seconds: float

    @property
    def refill_per_ms(self) -> float:
        return self.capacity / (self.window_seconds * 1000.0)

    @property
    def token_interval_seconds(self) -> float:
        return self.window_seconds / self.capacity


def parse_rate_limit(value: str) -> RateLimit:
    """Parse a rate limit string like '100/m' or '5/10s'."""
    match = _RATE_LIMIT_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(
            "rate_limit must match '<count>/<unit>' or '<count>/<multiplier><unit>'"
        )

    capacity = int(match.group(1))
    if capacity <= 0:
        raise ValueError("rate_limit count must be > 0")

    multiplier = int(match.group(2) or "1")
    if multiplier <= 0:
        raise ValueError("rate_limit window multiplier must be > 0")

    unit = match.group(3)
    window_seconds = multiplier * _UNIT_SECONDS[unit]
    return RateLimit(capacity=capacity, window_seconds=window_seconds)
