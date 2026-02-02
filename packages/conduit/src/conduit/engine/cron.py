"""Cron utilities for Conduit.

Provides cron scheduling functionality used by workers and jobs.

Example:
    import conduit

    worker = conduit.Worker("my-worker")

    @worker.cron("0 9 * * *")  # Every day at 9 AM UTC
    async def daily_report():
        stats = await compute_daily_stats()
        return {"sent": True}
"""

from datetime import UTC, datetime

from croniter import croniter


def calculate_next_cron_run(
    schedule: str,
    base_time: datetime | None = None,
) -> datetime:
    """
    Calculate the next run time for a cron schedule.

    Supports both 5-field (minute precision) and 6-field (second precision) formats.

    Args:
        schedule: Cron expression (5 or 6 fields)
        base_time: Time to calculate from (defaults to now)
        timezone: Timezone for evaluation (currently uses UTC)

    Returns:
        datetime of next run time (timezone-aware UTC)

    Examples:
        >>> # Every minute
        >>> next_run = calculate_next_cron_run("* * * * *")

        >>> # Every day at 9 AM
        >>> next_run = calculate_next_cron_run("0 9 * * *")

        >>> # Every second (6-field format)
        >>> next_run = calculate_next_cron_run("* * * * * *")
    """

    if base_time is None:
        base_time = datetime.now(UTC)
    elif base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=UTC)

    fields = schedule.split()

    if len(fields) == 6:
        # 6-field format with seconds at beginning
        cron_iter = croniter(schedule, base_time, second_at_beginning=True)
    else:
        # Standard 5-field format
        cron_iter = croniter(schedule, base_time)

    next_run = cron_iter.get_next(datetime)

    # croniter may return float or datetime depending on version/config
    if not isinstance(next_run, datetime):
        next_run = datetime.fromtimestamp(next_run, UTC)

    # Ensure timezone-aware
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=UTC)

    return next_run


def calculate_next_cron_timestamp(
    schedule: str,
    base_time: datetime | None = None,
) -> float:
    """
    Calculate the next run time for a cron schedule as Unix timestamp.

    Convenience wrapper around calculate_next_cron_run().

    Args:
        schedule: Cron expression (5 or 6 fields)
        base_time: Time to calculate from (defaults to now)
        timezone: Timezone for evaluation

    Returns:
        Unix timestamp of next run time
    """
    return calculate_next_cron_run(schedule, base_time).timestamp()
