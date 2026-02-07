# Cleanup TODO

Use this checklist to track reliability and correctness fixes found during code review.

- [x] **[P1] Prevent event loss when stream processing fails**
  The stream subscriber currently ACKs all events even when event processing throws, which can permanently drop job lifecycle updates on transient DB or validation errors.
  **What to update:** only ACK successfully applied events; keep failed IDs pending for retry/reclaim, and add structured logging/metrics for failed event IDs.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/services/stream_subscriber.py`

- [x] **[P1] Fix job metadata persistence path (`ctx.set_metadata` / checkpoint durability)**
  `update_job_metadata()` builds a key using `function=""`, so metadata writes often target a non-existent key and silently do nothing. It also uses `SET` which can drop TTL.
  **What to update:** locate the correct job key by ID (or add a stable job-id index), merge metadata on the actual stored job, and preserve TTL using `SETEX`/`EXPIRE` behavior.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/queue/redis/queue.py`

- [ ] **[P1] Make checkpoint persistence SQLAlchemy-safe**
  Checkpoint updates mutate `existing.metadata_` in place, and plain JSON columns do not always mark in-place mutations as dirty; updates may not commit.
  **What to update:** either reassign a new dict (`existing.metadata_ = {...}`) when checkpointing or use SQLAlchemy mutable JSON support for tracked in-place mutation.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/services/event_processing.py`

- [ ] **[P1] Guard `job.failed` updates against stale/out-of-order events**
  `job.started` has stale-attempt protections, but `job.failed` does not. Replay or out-of-order failed events can overwrite newer state.
  **What to update:** add attempt/time freshness checks before applying failure updates; ignore stale failure events consistently with started-event logic.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/services/event_processing.py`

- [ ] **[P2] Align jobs API filtering with request contract**
  The route accepts `worker_id` and multi-status query params, but repository filtering only supports a single status and does not apply worker filtering.
  **What to update:** extend repository query API to support `worker_id` and `status IN (...)`, then wire route params through directly.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/routes/jobs.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/db/repository.py`

- [ ] **[P2] Add graceful Redis-unavailable behavior for Redis-backed routes**
  Startup allows no-Redis mode, but several routes call `get_redis()` directly and can 500 if Redis is not connected.
  **What to update:** wrap Redis-backed handlers with graceful fallbacks (503 or empty payloads per endpoint contract), and keep behavior consistent across functions/workers/apis/events routes.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/routes/functions.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/routes/workers.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/routes/apis.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/routes/events.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/services/redis.py`

- [ ] **[P3] Make sweeper distributed-lock release ownership-safe**
  Sweeper lock release currently uses unconditional `DEL`; if lock TTL expires and another instance acquires it, the first instance can accidentally delete the new owner’s lock.
  **What to update:** store a lock token and release via compare-and-delete Lua script (same pattern used in cleanup service lock release).
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/queue/redis/sweeper.py`

- [ ] **[P3] Normalize `Worker.execute()` started-attempt numbering**
  Direct `Worker.execute()` emits `job.started` with attempt `0`, while the model and normal worker flow treat started attempts as 1-indexed.
  **What to update:** increment/mark attempt before emitting `job.started` (or emit `attempt=1` explicitly) so event semantics stay consistent across execution modes.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/sdk/worker.py`, `/Users/connormclean/Documents/programs/conduit/packages/shared/src/shared/models.py`

- [ ] **[P1] Implement real cancel/retry behavior in jobs API**
  `POST /jobs/{job_id}/cancel` and `POST /jobs/{job_id}/retry` are placeholder stubs that return success-like responses without actually driving queue state.
  **What to update:** wire both endpoints to queue operations (or explicit `501 Not Implemented` until done), enforce state validation, and return truthful status/result payloads.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/routes/jobs.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/services/queue.py`

- [ ] **[P1] Ensure schema readiness for PostgreSQL startup**
  Server startup only connects for PostgreSQL and assumes schema is already migrated; missing migrations can cause runtime failures after boot.
  **What to update:** add startup guard to validate required tables/schema version (or run migrations as part of deploy/startup workflow), and fail fast with clear error if schema is stale.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/main.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/alembic/env.py`

- [ ] **[P2] Replace approximate jobs total with deterministic count**
  Jobs list currently reports `total=len(page)+offset`, which is not the real total and can break pagination semantics in UI/manual testing.
  **What to update:** add a count query with matching filters and return exact total (or explicitly rename field/contract if approximation is intended).
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/routes/jobs.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/db/repository.py`

- [ ] **[P1] Fix SDK parallel helpers contract mismatch (`submit` return type)**
  `sdk.parallel.map_tasks` and `submit_many` assume `task.submit()` returns `Future`, but `TaskHandle.submit()` currently returns `job_id: str`. This breaks these helpers at runtime (`str` has no `.result()`).
  **What to update:** unify the contract: either make `TaskHandle.submit()` return `Future` or update parallel helpers to work with job IDs plus queue access. Ensure `gather/submit_many/map_tasks` examples match real behavior.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/sdk/parallel.py`, `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/handlers/task_handle.py`, `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/sdk/task.py`

- [ ] **[P1] Remove hidden 30s timeout from `TaskHandle.wait()`**
  `TaskHandle.wait()` calls `queue.subscribe_job(job_id)` with default timeout (30s). Long-running tasks can time out even when worker/task timeouts are much longer.
  **What to update:** add explicit `timeout` parameter to `wait()`/`wait_sync()` (or default to task timeout/no timeout), pass through to `subscribe_job`, and document expected behavior.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/handlers/task_handle.py`, `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/queue/base.py`, `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/queue/redis/queue.py`

- [ ] **[P2] Apply `--only` filtering before worker initialization in CLI run**
  `conduit run` initializes all discovered workers before applying `--only` filters. Running API-only subsets can still fail due to unrelated worker Redis requirements.
  **What to update:** filter components first, then initialize only workers that will actually run.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/cli/run.py`, `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/cli/_display.py`

- [ ] **[P1] Fail fast when any service task crashes during `run_services` startup/runtime**
  `run_services()` waits only on shutdown signal and does not monitor API/worker task failures. A crashed worker/API task can silently die while process keeps running.
  **What to update:** monitor service tasks with `asyncio.wait(..., FIRST_EXCEPTION)` or done callbacks, surface exceptions, trigger coordinated shutdown, and exit non-zero on unrecoverable startup/runtime failures.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/runner.py`

- [ ] **[P2] Add `conduit server start` CLI command for hosted server startup**
  There is currently no first-class Conduit CLI command to start the actual hosted server implementation in `packages/server`.
  **What to update:** add a new CLI subcommand (e.g. `conduit server start`) that launches `server.main:app` with configurable host/port/reload and clear env wiring (`CONDUIT_DATABASE_URL`, `CONDUIT_REDIS_URL`). Reuse existing CLI logging/error UX and document usage.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/cli/__init__.py`, `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/cli/run.py`, `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/main.py`

- [ ] **[P1] Do not mark stream consumer group as initialized after failed creation**
  `StreamSubscriber._ensure_consumer_group()` sets `_group_created=True` even when group creation fails for reasons other than `BUSYGROUP`. This can leave subscriber stuck in a degraded loop that never retries proper group creation.
  **What to update:** set `_group_created=True` only on success or confirmed `BUSYGROUP`; keep retry path for transient Redis errors.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/server/src/server/services/stream_subscriber.py`

- [ ] **[P1] Fix process executor path for sync tasks (unpicklable context object)**
  Process mode currently sends `ctx_copy.run` to `ProcessPoolExecutor`. `_contextvars.Context` is not picklable, so this path fails for process-based execution.
  **What to update:** avoid passing `contextvars.Context` into process workers; invoke a picklable wrapper/call target for process mode and define a clear context-behavior policy for process tasks.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/src/conduit/engine/job_processor.py`

- [ ] **[P2] Fix default SDK Docker image command path**
  `packages/conduit/Dockerfile` default CMD runs `conduit run examples/service.py`, but the image does not copy the `examples/` directory. Default container startup can fail with file-not-found.
  **What to update:** either copy `examples/` into the image or change default CMD to a valid in-image target/help command.
  **Primary files:** `/Users/connormclean/Documents/programs/conduit/packages/conduit/Dockerfile`
