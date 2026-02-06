"""Functions routes - aggregate stats from jobs table."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from shared.schemas import (
    FunctionDetailResponse,
    FunctionInfo,
    FunctionsListResponse,
    FunctionType,
    HourlyStat,
    Run,
)

from server.db.repository import JobRepository
from server.db.session import get_database
from server.services import get_function_definitions
from server.services.workers import list_worker_instances

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/functions", tags=["functions"])


def _build_function_info(
    name: str,
    config: dict[str, Any],
    *,
    active: bool = False,
    workers: list[str] | None = None,
    runs_24h: int = 0,
    success_rate: float = 100.0,
    avg_duration_ms: float = 0,
    p95_duration_ms: float | None = None,
    last_run_at: str | None = None,
    last_run_status: str | None = None,
) -> FunctionInfo:
    """Build a FunctionInfo from a config dict and stats."""
    return FunctionInfo(
        name=name,
        type=config.get("type", "task"),
        active=active,
        timeout=config.get("timeout"),
        max_retries=config.get("max_retries"),
        retry_delay=config.get("retry_delay"),
        schedule=config.get("schedule"),
        timezone=config.get("timezone"),
        next_run_at=config.get("next_run_at"),
        pattern=config.get("pattern"),
        source=config.get("source"),
        batch_size=config.get("batch_size"),
        batch_timeout=config.get("batch_timeout"),
        max_concurrency=config.get("max_concurrency"),
        workers=workers or [],
        runs_24h=runs_24h,
        success_rate=success_rate,
        avg_duration_ms=avg_duration_ms,
        p95_duration_ms=p95_duration_ms,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
        events_processed_24h=config.get("events_processed_24h"),
        batches_24h=config.get("batches_24h"),
    )


@router.get("", response_model=FunctionsListResponse)
async def list_functions(
    type: FunctionType | None = Query(None, description="Filter by function type"),
) -> FunctionsListResponse:
    """
    List all functions with stats aggregated from jobs table.

    Stats are computed from job history for the last 24 hours.
    """
    functions: list[FunctionInfo] = []
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    # Fetch function definitions and active workers from Redis
    func_defs = await get_function_definitions()
    active_workers = await list_worker_instances()

    # Build function → worker instance counts (deduplicated by name)
    # Workers register handler names (e.g., "on_order_send_confirmation") in their
    # functions list, so worker labels are keyed by handler name directly.
    func_worker_counts: dict[str, dict[str, int]] = {}
    for w in active_workers:
        label = w.worker_name or w.hostname or w.id[:8]
        for fn_name in w.functions:
            counts = func_worker_counts.setdefault(fn_name, {})
            counts[label] = counts.get(label, 0) + 1

    # Collapse into deduplicated labels: "name (3)" for multiple instances
    func_worker_labels: dict[str, list[str]] = {}
    for fn_name, counts in func_worker_counts.items():
        labels = []
        for label, count in counts.items():
            labels.append(f"{label} ({count})" if count > 1 else label)
        func_worker_labels[fn_name] = labels

    # Build handler → event config mapping so we show handler names instead of pattern names
    # e.g., show "on_order_send_confirmation" (EVENT, pattern: order.placed)
    # instead of "order.placed" (EVENT, pattern: order.placed) which is redundant
    handler_to_event: dict[str, tuple[str, dict]] = {}
    event_patterns_with_handlers: set[str] = set()
    for name, config in func_defs.items():
        if config.get("type") == "event" and config.get("handlers"):
            event_patterns_with_handlers.add(name)
            for handler_name in config["handlers"]:
                handler_to_event[handler_name] = (name, config)

    # Determine if a function is active (any live worker lists it)
    # func_worker_labels is derived from live worker heartbeats (TTL-based),
    # so it's the reliable source of truth. func_defs keys may be stale.
    active_func_names: set[str] = set(func_worker_labels.keys())

    def is_func_active(name: str) -> bool:
        return name in active_func_names

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            # Get aggregated stats per function (SQL GROUP BY instead of fetching all rows)
            func_stats = await repo.get_function_job_stats(start_date=day_ago)

            # Build function list from aggregated stats
            for name, stats in func_stats.items():
                # Skip event pattern entries - they're expanded into handler entries below
                if name in event_patterns_with_handlers:
                    continue

                # If this is a handler for an event, use the parent event config
                if name in handler_to_event:
                    _, func_config = handler_to_event[name]
                else:
                    func_config = func_defs.get(name, {"type": "task"})

                func_type = func_config.get("type", "task")
                if type and func_type != type:
                    continue

                runs = stats["runs"]
                success_rate = (stats["successes"] / runs * 100) if runs > 0 else 100.0

                functions.append(
                    _build_function_info(
                        name,
                        func_config,
                        active=is_func_active(name),
                        workers=func_worker_labels.get(name, []),
                        runs_24h=runs,
                        success_rate=round(success_rate, 1),
                        avg_duration_ms=stats["avg_duration_ms"],
                        last_run_at=stats["last_run_at"],
                        last_run_status=stats["last_run_status"],
                    )
                )

            # Also add registered functions with no runs
            for name, config in func_defs.items():
                func_type = config.get("type", "task")
                if type and func_type != type:
                    continue

                # For events with handlers, expand into one entry per handler
                if name in event_patterns_with_handlers:
                    for handler_name in config.get("handlers", []):
                        if handler_name not in func_stats:
                            functions.append(
                                _build_function_info(
                                    handler_name,
                                    config,
                                    active=is_func_active(handler_name),
                                    workers=func_worker_labels.get(handler_name, []),
                                )
                            )
                elif name not in func_stats:
                    functions.append(
                        _build_function_info(
                            name,
                            config,
                            active=is_func_active(name),
                            workers=func_worker_labels.get(name, []),
                        )
                    )

    except RuntimeError:
        # Database not available - return registered functions only
        for name, config in func_defs.items():
            func_type = config.get("type", "task")
            if type and func_type != type:
                continue

            if name in event_patterns_with_handlers:
                for handler_name in config.get("handlers", []):
                    functions.append(
                        _build_function_info(
                            handler_name,
                            config,
                            active=is_func_active(handler_name),
                            workers=func_worker_labels.get(handler_name, []),
                        )
                    )
            else:
                functions.append(
                    _build_function_info(
                        name,
                        config,
                        active=is_func_active(name),
                        workers=func_worker_labels.get(name, []),
                    )
                )

    # Sort by runs (most active first)
    functions.sort(key=lambda f: f.runs_24h, reverse=True)

    return FunctionsListResponse(functions=functions, total=len(functions))


@router.get("/{name}", response_model=FunctionDetailResponse)
async def get_function(name: str) -> FunctionDetailResponse:
    """
    Get detailed info for a specific function.

    Includes recent runs and hourly stats.
    """
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    # Fetch function definitions and active workers from Redis
    func_defs = await get_function_definitions()
    active_workers = await list_worker_instances()
    func_config = func_defs.get(name, {"type": "task"})
    func_type = func_config.get("type", "task")

    # Active if any live worker lists this function
    is_active = any(name in w.functions for w in active_workers)

    recent_runs: list[Run] = []
    hourly_stats: list[HourlyStat] = []

    # Initialize hourly buckets
    hourly_buckets: dict[str, dict[str, int]] = {}
    for i in range(24):
        hour = (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:00:00Z")
        hourly_buckets[hour] = {"success": 0, "failure": 0}

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            # Get recent jobs for this function
            jobs = await repo.list_jobs(function=name, start_date=day_ago, limit=100)

            runs = 0
            successes = 0
            total_duration_ms = 0
            duration_count = 0
            last_run_at = None
            last_run_status = None

            for job in jobs:
                runs += 1

                # Track success/failure
                if job.status == "complete":
                    successes += 1
                    # Add to hourly bucket
                    if job.completed_at:
                        hour = job.completed_at.strftime("%Y-%m-%dT%H:00:00Z")
                        if hour in hourly_buckets:
                            hourly_buckets[hour]["success"] += 1
                elif job.status == "failed":
                    if job.completed_at:
                        hour = job.completed_at.strftime("%Y-%m-%dT%H:00:00Z")
                        if hour in hourly_buckets:
                            hourly_buckets[hour]["failure"] += 1

                # Calculate duration
                duration_ms = None
                if job.started_at and job.completed_at:
                    duration_ms = (
                        job.completed_at - job.started_at
                    ).total_seconds() * 1000
                    total_duration_ms += duration_ms
                    duration_count += 1

                # Track last run
                run_time = job.completed_at or job.started_at or job.created_at
                if run_time and (
                    last_run_at is None or run_time.isoformat() > last_run_at
                ):
                    last_run_at = run_time.isoformat()
                    last_run_status = job.status

                # Add to recent runs (limit to 20)
                if len(recent_runs) < 20:
                    recent_runs.append(
                        Run(
                            id=job.id,
                            function=job.function,
                            status=job.status,
                            started_at=job.started_at.isoformat()
                            if job.started_at
                            else None,
                            completed_at=job.completed_at.isoformat()
                            if job.completed_at
                            else None,
                            duration_ms=duration_ms,
                            error=job.error,
                        )
                    )

            success_rate = (successes / runs * 100) if runs > 0 else 100.0
            avg_duration = (
                (total_duration_ms / duration_count) if duration_count > 0 else 0
            )

            # Convert hourly buckets to list (sorted by hour, most recent first)
            for hour in sorted(hourly_buckets.keys(), reverse=True):
                hourly_stats.append(
                    HourlyStat(
                        hour=hour,
                        success=hourly_buckets[hour]["success"],
                        failure=hourly_buckets[hour]["failure"],
                    )
                )

            return FunctionDetailResponse(
                name=name,
                type=func_type,
                active=is_active,
                timeout=func_config.get("timeout"),
                max_retries=func_config.get("max_retries"),
                retry_delay=func_config.get("retry_delay"),
                schedule=func_config.get("schedule"),
                timezone=func_config.get("timezone"),
                next_run_at=func_config.get("next_run_at"),
                pattern=func_config.get("pattern"),
                source=func_config.get("source"),
                batch_size=func_config.get("batch_size"),
                batch_timeout=func_config.get("batch_timeout"),
                max_concurrency=func_config.get("max_concurrency"),
                runs_24h=runs,
                success_rate=round(success_rate, 1),
                avg_duration_ms=round(avg_duration, 2),
                p95_duration_ms=None,
                last_run_at=last_run_at,
                last_run_status=last_run_status,
                recent_runs=recent_runs,
                hourly_stats=hourly_stats,
            )

    except RuntimeError:
        # Database not available
        return FunctionDetailResponse(
            name=name,
            type=func_type,
            active=is_active,
            runs_24h=0,
            success_rate=100.0,
            avg_duration_ms=0,
            recent_runs=[],
            hourly_stats=[],
        )
