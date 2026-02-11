"""Functions routes - aggregate stats from jobs table."""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from shared.schemas import (
    FunctionDetailResponse,
    FunctionConfig,
    FunctionInfo,
    FunctionsListResponse,
    FunctionType,
    Run,
)

from server.db.repository import FunctionJobStats, FunctionWaitStats, JobRepository
from server.db.session import get_database
from server.routes.functions_utils import set_function_pause_state
from server.services import get_function_definitions, get_function_queue_depth_stats
from server.services.workers import list_worker_instances

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/functions", tags=["functions"])


def _build_function_info(
    key: str,
    config: FunctionConfig,
    *,
    active: bool = False,
    workers: list[str] | None = None,
    runs_24h: int = 0,
    success_rate: float = 100.0,
    avg_duration_ms: float = 0,
    p95_duration_ms: float | None = None,
    avg_wait_ms: float | None = None,
    p95_wait_ms: float | None = None,
    queue_backlog: int = 0,
    last_run_at: str | None = None,
    last_run_status: str | None = None,
) -> FunctionInfo:
    """Build a FunctionInfo from a config dict and stats."""
    return FunctionInfo(
        key=key,
        name=config.name,
        type=config.type,
        active=active,
        paused=config.paused,
        timeout=config.timeout,
        max_retries=config.max_retries,
        retry_delay=config.retry_delay,
        rate_limit=config.rate_limit,
        max_concurrency=config.max_concurrency,
        routing_group=config.routing_group,
        group_max_concurrency=config.group_max_concurrency,
        schedule=config.schedule,
        next_run_at=config.next_run_at,
        missed_run_policy=config.missed_run_policy,
        max_catch_up_seconds=config.max_catch_up_seconds,
        pattern=config.pattern,
        workers=workers or [],
        runs_24h=runs_24h,
        success_rate=success_rate,
        avg_duration_ms=avg_duration_ms,
        p95_duration_ms=p95_duration_ms,
        avg_wait_ms=avg_wait_ms,
        p95_wait_ms=p95_wait_ms,
        queue_backlog=queue_backlog,
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

    try:
        func_defs = await get_function_definitions()
        active_workers = await list_worker_instances()
    except RuntimeError:
        func_defs = {}
        active_workers = []
    try:
        queue_depth_by_function = await get_function_queue_depth_stats()
    except RuntimeError:
        queue_depth_by_function = {}

    # Build function-key -> worker labels (deduplicated by worker name).
    func_worker_counts: dict[str, dict[str, int]] = {}
    for worker in active_workers:
        label = worker.worker_name or worker.hostname or worker.id[:8]
        for function_key in worker.functions:
            counts = func_worker_counts.setdefault(function_key, {})
            counts[label] = counts.get(label, 0) + 1

    func_worker_labels: dict[str, list[str]] = {}
    for function_key, counts in func_worker_counts.items():
        labels = []
        for label, count in counts.items():
            labels.append(f"{label} ({count})" if count > 1 else label)
        func_worker_labels[function_key] = labels

    active_function_keys = set(func_worker_labels.keys())

    def is_func_active(function_key: str) -> bool:
        return function_key in active_function_keys

    func_stats: dict[str, FunctionJobStats] = {}
    wait_stats: dict[str, FunctionWaitStats] = {}
    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)
            func_stats = await repo.get_function_job_stats(start_date=day_ago)
            wait_stats = await repo.get_function_wait_stats(start_date=day_ago)
    except RuntimeError:
        pass

    all_keys = set(func_defs.keys()) | set(func_stats.keys())
    for function_key in all_keys:
        config = func_defs.get(
            function_key,
            FunctionConfig(key=function_key, name=function_key, type=FunctionType.TASK),
        )
        func_type = config.type
        if type and func_type != type:
            continue

        stats = func_stats.get(function_key)
        queue_depth = queue_depth_by_function.get(function_key)
        queue_backlog = queue_depth.backlog if queue_depth else 0
        wait = wait_stats.get(function_key)
        if stats is None:
            functions.append(
                _build_function_info(
                    function_key,
                    config,
                    active=is_func_active(function_key),
                    workers=func_worker_labels.get(function_key, []),
                    queue_backlog=queue_backlog,
                    avg_wait_ms=wait.avg_wait_ms if wait else None,
                    p95_wait_ms=wait.p95_wait_ms if wait else None,
                )
            )
            continue

        runs = stats.runs
        success_rate = (stats.successes / runs * 100) if runs > 0 else 100.0
        functions.append(
            _build_function_info(
                function_key,
                config,
                active=is_func_active(function_key),
                workers=func_worker_labels.get(function_key, []),
                runs_24h=runs,
                success_rate=round(success_rate, 1),
                avg_duration_ms=stats.avg_duration_ms,
                avg_wait_ms=wait.avg_wait_ms if wait else None,
                p95_wait_ms=wait.p95_wait_ms if wait else None,
                queue_backlog=queue_backlog,
                last_run_at=stats.last_run_at,
                last_run_status=stats.last_run_status,
            )
        )

    functions.sort(key=lambda f: (-f.queue_backlog, -f.runs_24h, f.name, f.key))
    return FunctionsListResponse(functions=functions, total=len(functions))


@router.get("/{name}", response_model=FunctionDetailResponse)
async def get_function(name: str) -> FunctionDetailResponse:
    """Get detailed info for a specific function key."""
    now = datetime.now(UTC)
    day_ago = now - timedelta(hours=24)
    function_key = name

    try:
        func_defs = await get_function_definitions()
        active_workers = await list_worker_instances()
    except RuntimeError:
        func_defs = {}
        active_workers = []
    try:
        queue_depth_by_function = await get_function_queue_depth_stats()
    except RuntimeError:
        queue_depth_by_function = {}

    func_config = func_defs.get(
        function_key,
        FunctionConfig(key=function_key, name=function_key, type=FunctionType.TASK),
    )
    func_type = func_config.type

    worker_counts: dict[str, int] = {}
    for worker in active_workers:
        if function_key in worker.functions:
            label = worker.worker_name or worker.hostname or worker.id[:8]
            worker_counts[label] = worker_counts.get(label, 0) + 1

    worker_labels = [
        f"{label} ({count})" if count > 1 else label
        for label, count in worker_counts.items()
    ]
    is_active = len(worker_labels) > 0

    runs_24h = 0
    success_rate = 100.0
    avg_duration_ms = 0.0
    p95_duration_ms: float | None = None
    avg_wait_ms: float | None = None
    p95_wait_ms: float | None = None
    last_run_at: str | None = None
    last_run_status: str | None = None
    recent_runs: list[Run] = []

    try:
        db = get_database()
        async with db.session() as session:
            repo = JobRepository(session)

            stats = await repo.get_stats(function=function_key, start_date=day_ago)
            runs_24h = stats["total"]
            success_rate = round(stats["success_rate"], 1)
            wait_stats = await repo.get_function_wait_stats(
                start_date=day_ago,
                function=function_key,
            )
            function_wait = wait_stats.get(function_key)
            if function_wait:
                avg_wait_ms = function_wait.avg_wait_ms
                p95_wait_ms = function_wait.p95_wait_ms

            durations = await repo.get_durations(
                function=function_key, start_date=day_ago
            )
            if durations:
                avg_duration_ms = round(sum(durations) / len(durations), 2)
                p95_idx = min(math.ceil(len(durations) * 0.95) - 1, len(durations) - 1)
                p95_duration_ms = round(durations[p95_idx], 2)

            jobs = await repo.list_jobs(function=function_key, limit=20)
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
                        function_name=job.function_name,
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

    queue_depth = queue_depth_by_function.get(function_key)
    queue_backlog = queue_depth.backlog if queue_depth else 0

    return FunctionDetailResponse(
        key=function_key,
        name=func_config.name,
        type=func_type,
        active=is_active,
        paused=func_config.paused,
        workers=worker_labels,
        timeout=func_config.timeout,
        max_retries=func_config.max_retries,
        retry_delay=func_config.retry_delay,
        rate_limit=func_config.rate_limit,
        max_concurrency=func_config.max_concurrency,
        routing_group=func_config.routing_group,
        group_max_concurrency=func_config.group_max_concurrency,
        schedule=func_config.schedule,
        next_run_at=func_config.next_run_at,
        missed_run_policy=func_config.missed_run_policy,
        max_catch_up_seconds=func_config.max_catch_up_seconds,
        pattern=func_config.pattern,
        runs_24h=runs_24h,
        success_rate=success_rate,
        avg_duration_ms=avg_duration_ms,
        p95_duration_ms=p95_duration_ms,
        avg_wait_ms=avg_wait_ms,
        p95_wait_ms=p95_wait_ms,
        queue_backlog=queue_backlog,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
        recent_runs=recent_runs,
    )

@router.post("/{name}/pause")
async def pause_function(name: str) -> dict[str, Any]:
    """Pause dispatch for a function key."""
    try:
        payload = await set_function_pause_state(name, paused=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Function '{name}' not found")
    return payload


@router.post("/{name}/resume")
async def resume_function(name: str) -> dict[str, Any]:
    """Resume dispatch for a function key."""
    try:
        payload = await set_function_pause_state(name, paused=False)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Function '{name}' not found")
    return payload
