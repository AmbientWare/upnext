from datetime import UTC, datetime


def as_utc_aware(value: datetime | None) -> datetime | None:
    """Normalize DB datetimes to UTC-aware before arithmetic."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
