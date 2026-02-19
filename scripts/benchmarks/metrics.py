from __future__ import annotations

from statistics import mean, median, pstdev


def percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * pct))))
    return ordered[idx]


def sample_summary(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "stdev": 0.0,
        }
    return {
        "p50": percentile(samples, 0.50),
        "p95": percentile(samples, 0.95),
        "p99": percentile(samples, 0.99),
        "max": max(samples),
        "mean": mean(samples),
        "median": median(samples),
        "stdev": pstdev(samples) if len(samples) > 1 else 0.0,
    }


def seconds_to_ms(samples: list[float]) -> list[float]:
    return [value * 1000.0 for value in samples]
