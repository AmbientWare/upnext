"""Functions routes - aggregate stats from jobs table."""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from shared.schemas import (
    FunctionDetailResponse,
    FunctionInfo,
    FunctionsListResponse,
    FunctionType,
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
        type=config.get("type", FunctionType.TASK),
        active=active,
        timeout=config.get("timeout"),
        max_retries=config.get("max_retries"),
        retry_delay=config.get("retry_delay"),
        schedule=config.get("schedule"),
        next_run_at=config.get("next_run_at"),
        pattern=config.get("pattern"),
        workers=workers or [],
        runs_24h=runs_24h,
        success_rate=success_rate,
        avg_duration_ms=avg_duration_ms,
        p95_duration_ms=p95_duration_ms,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
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
        if config.get("type") == FunctionType.EVENT and config.get("handlers"):
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
                    func_config = func_defs.get(name, {"type": FunctionType.TASK})

                func_type = func_config.get("type", FunctionType.TASK)
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
                func_type = config.get("type", FunctionType.TASK)
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
            func_type = config.get("type", FunctionType.TASK)
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
    """Get detailed info for a specific function."""
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)

    # Fetch function definitions and active workers from Redis
    func_defs = await get_function_definitions()
    active_workers = await list_worker_instances()

    # If this is an event handler name, resolve to the parent event config
    func_config = func_defs.get(name, {"type": FunctionType.TASK})
    for _pattern, config in func_defs.items():
        if config.get("type") == FunctionType.EVENT and name in config.get("handlers", []):
            func_config = config
            break
    func_type = func_config.get("type", FunctionType.TASK)

    # Build worker labels for this function
    worker_counts: dict[str, int] = {}
    for w in active_workers:
        if name in w.functions:
            label = w.worker_name or w.hostname or w.id[:8]
            worker_counts[label] = worker_counts.get(label, 0) + 1

    worker_labels = [
        f"{label} ({count})" if count > 1 else label
        for label, count in worker_counts.items()
    ]
    is_active = len(worker_labels) > 0

    # Defaults
    runs_24h = 0
    success_rate = 100.0
    avg_duration_ms = 0.0
    p95_duration_ms: float | None = None
    last_run_at: str | None = None
    last_run_status: str | None = None
    recent_runs: list[Run] = []

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            # Accurate counts via SQL aggregation (not capped by LIMIT)
            stats = await repo.get_stats(function=name, start_date=day_ago)
            runs_24h = stats["total"]
            success_rate = round(stats["success_rate"], 1)

            # All durations (pre-sorted) for avg + p95
            durations = await repo.get_durations(
                function=name, start_date=day_ago
            )
            if durations:
                avg_duration_ms = round(sum(durations) / len(durations), 2)
                p95_idx = min(
                    math.ceil(len(durations) * 0.95) - 1, len(durations) - 1
                )
                p95_duration_ms = round(durations[p95_idx], 2)

            # Recent runs for the table (also gives us last run info)
            jobs = await repo.list_jobs(function=name, limit=20)
            if jobs:
                first = jobs[0]
                run_time = first.completed_at or first.started_at or first.created_at
                if run_time:
                    last_run_at = run_time.isoformat()
                last_run_status = first.status

            for job in jobs:
                duration_ms = None
                if job.started_at and job.completed_at:
                    duration_ms = (
                        job.completed_at - job.started_at
                    ).total_seconds() * 1000

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

    except RuntimeError:
        pass

    return FunctionDetailResponse(
        name=name,
        type=func_type,
        active=is_active,
        workers=worker_labels,
        timeout=func_config.get("timeout"),
        max_retries=func_config.get("max_retries"),
        retry_delay=func_config.get("retry_delay"),
        schedule=func_config.get("schedule"),
        next_run_at=func_config.get("next_run_at"),
        pattern=func_config.get("pattern"),
        runs_24h=runs_24h,
        success_rate=success_rate,
        avg_duration_ms=avg_duration_ms,
        p95_duration_ms=p95_duration_ms,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
        recent_runs=recent_runs,
    )
