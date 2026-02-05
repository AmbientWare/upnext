"""Functions routes - aggregate stats from jobs table."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from server.db.repository import JobRepository
from server.db.session import get_database
from server.services import get_function_definitions
from shared.schemas import (
    FunctionDetailResponse,
    FunctionInfo,
    FunctionsListResponse,
    FunctionType,
    HourlyStat,
    Run,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/functions", tags=["functions"])


@router.get("/", response_model=FunctionsListResponse)
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

    # Fetch function definitions from Redis once
    func_defs = await get_function_definitions()

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            # Get all jobs from last 24 hours
            jobs = await repo.list_jobs(start_date=day_ago, limit=10000)

            # Group by function name
            func_stats: dict[str, dict[str, Any]] = {}
            for job in jobs:
                name = job.function
                if name not in func_stats:
                    func_stats[name] = {
                        "runs": 0,
                        "successes": 0,
                        "failures": 0,
                        "total_duration_ms": 0,
                        "duration_count": 0,
                        "last_run_at": None,
                        "last_run_status": None,
                    }

                stats = func_stats[name]
                stats["runs"] += 1

                if job.status == "complete":
                    stats["successes"] += 1
                elif job.status == "failed":
                    stats["failures"] += 1

                # Calculate duration if we have both timestamps
                if job.started_at and job.completed_at:
                    duration_ms = (
                        job.completed_at - job.started_at
                    ).total_seconds() * 1000
                    stats["total_duration_ms"] += duration_ms
                    stats["duration_count"] += 1

                # Track last run
                run_time = job.completed_at or job.started_at or job.created_at
                if run_time and (
                    stats["last_run_at"] is None
                    or run_time
                    > datetime.fromisoformat(
                        stats["last_run_at"].replace("Z", "+00:00")
                    )
                ):
                    stats["last_run_at"] = run_time.isoformat()
                    stats["last_run_status"] = job.status

            # Build function list from stats
            for name, stats in func_stats.items():
                # Determine function type from registered functions or default to task
                func_config = func_defs.get(name, {"type": "task"})
                func_type = func_config.get("type", "task")

                # Filter by type if specified
                if type and func_type != type:
                    continue

                runs = stats["runs"]
                success_rate = (stats["successes"] / runs * 100) if runs > 0 else 100.0
                avg_duration = (
                    (stats["total_duration_ms"] / stats["duration_count"])
                    if stats["duration_count"] > 0
                    else 0
                )

                functions.append(
                    FunctionInfo(
                        name=name,
                        type=func_type,
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
                        p95_duration_ms=None,  # Would need more complex calculation
                        last_run_at=stats["last_run_at"],
                        last_run_status=stats["last_run_status"],
                        events_processed_24h=func_config.get("events_processed_24h"),
                        batches_24h=func_config.get("batches_24h"),
                    )
                )

            # Also add registered functions with no runs
            for name, config in func_defs.items():
                func_type = config.get("type", "task")
                if type and func_type != type:
                    continue
                if name not in func_stats:
                    functions.append(
                        FunctionInfo(
                            name=name,
                            type=func_type,
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
                            runs_24h=0,
                            success_rate=100.0,
                            avg_duration_ms=0,
                            p95_duration_ms=None,
                            last_run_at=None,
                            last_run_status=None,
                        )
                    )

    except RuntimeError:
        # Database not available - return registered functions only
        for name, config in func_defs.items():
            func_type = config.get("type", "task")
            if type and func_type != type:
                continue
            functions.append(
                FunctionInfo(
                    name=name,
                    type=func_type,
                    timeout=config.get("timeout"),
                    max_retries=config.get("max_retries"),
                    retry_delay=config.get("retry_delay"),
                    schedule=config.get("schedule"),
                    pattern=config.get("pattern"),
                    runs_24h=0,
                    success_rate=100.0,
                    avg_duration_ms=0,
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

    # Fetch function definitions from Redis
    func_defs = await get_function_definitions()
    func_config = func_defs.get(name, {"type": "task"})
    func_type = func_config.get("type", "task")

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
            runs_24h=0,
            success_rate=100.0,
            avg_duration_ms=0,
            recent_runs=[],
            hourly_stats=[],
        )
