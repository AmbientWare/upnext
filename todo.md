# Conduit TODO

## Specific Issues

### 1. `inspect.signature()` called on every job execution
`_call_function` introspects the function signature on every job run to check if it wants `ctx`. Same in `task_wants_context()`. Should be computed once at registration time.

- [x] Add `wants_context: bool` field to `TaskDefinition`
- [x] Compute it in `Registry.register_task()` using `inspect.signature`
- [x] Update `JobProcessor._call_function()` to read `task_def.wants_context` instead of calling `inspect.signature`
- [x] Update `TaskHandle.__call__()` and `task_wants_context()` to use the cached value
- [x] Remove standalone `task_wants_context()` function or make it a one-time helper used only at registration

### 2. Context not serializable + async-only methods broken for sync tasks
Two problems: (a) `Context._backend` holds `JobContextBackend` with Redis connections and asyncio objects — not picklable, so `SyncExecutor.PROCESS` raises `PicklingError`. (b) All Context methods (`set_progress`, `set_metadata`, etc.) are `async def`, so sync tasks (thread pool or process pool) can't call them at all.

**Solution: serializable Context + sync methods + command queue drained by event loop.**

Context becomes a plain data object with sync methods. Methods push commands onto a queue. A drain task in the event loop reads commands and executes them against the real backend. The queue type varies by executor mode:

| Mode | Queue type | Why |
|------|-----------|-----|
| Async | `asyncio.Queue` | No serialization, event loop native |
| Thread pool | `queue.Queue` | No pickling (shared memory), thread-safe |
| Process pool | `multiprocessing.Queue` | Picklable, crosses process boundary |

#### Context changes
- [x] Remove `_backend` field from `Context`
- [x] Remove `_logger` field (not picklable) — recreate lazily from `job_id`
- [x] Add `_cmd_queue: Any = field(default=None, repr=False)` field (holds whichever queue type)
- [x] Make `Context` fully serializable (all remaining fields must be JSON/pickle safe)
- [x] Change `set_progress` from `async def` to `def` — puts `("set_progress", job_id, progress)` on `_cmd_queue`
- [x] Change `set_metadata` from `async def` to `def` — updates local `_metadata` dict and puts command on queue
- [x] Change `checkpoint` from `async def` to `def` — puts command on queue
- [x] Change `send_log` from `async def` to `def` — puts command on queue
- [x] `get_metadata` stays sync, reads from local `_metadata` dict only (already cached). Drop the async backend fallback, or keep it as a separate `async get_metadata_from_backend()` for async tasks that need it

#### Command drain task
- [x] Create `_drain_commands(cmd_queue, backend)` coroutine in `JobProcessor`
- [x] Drain reads from queue, dispatches to `JobContextBackend` methods (`set_progress`, `set_metadata`, `checkpoint`, `log`)
- [x] For `asyncio.Queue`: use `await queue.get()` directly
- [x] For `queue.Queue`: use `await loop.run_in_executor(None, queue.get, True, 0.1)` with timeout to avoid blocking
- [x] For `multiprocessing.Queue`: same `run_in_executor` pattern
- [x] Drain task is started per-job in `_execute_job`, cancelled/joined after job completes
- [x] Send sentinel `None` to signal drain task to exit cleanly

#### JobProcessor changes
- [x] In `_call_function`, create the right queue type based on `self._sync_pool` type (or `task_def.is_async`)
- [x] Attach queue to Context: `ctx._cmd_queue = cmd_queue`
- [x] Start drain task before calling the function
- [x] After function returns, send sentinel and await drain task to flush remaining commands
- [x] For async tasks: can skip the drain task entirely and use a ContextVar backend directly if simpler (optimization, not required)

#### Update usages
- [x] Update all call sites that `await ctx.set_progress(...)` → `ctx.set_progress(...)`
- [x] Update all call sites that `await ctx.set_metadata(...)` → `ctx.set_metadata(...)`
- [x] Update all call sites that `await ctx.checkpoint(...)` → `ctx.checkpoint(...)`
- [x] Update all call sites that `await ctx.send_log(...)` → `ctx.send_log(...)`
- [x] Update tests

### 3. Fire-and-forget tasks are untracked (GC risk)
`TaskHandle.send()` and `EventHandle.trigger()` both call `asyncio.create_task()` without storing references. Python can garbage-collect these before completion.

- [x] Add `_background_tasks: set[asyncio.Task]` to `Worker`
- [x] Pass reference to `TaskHandle` and `EventHandle` (or have them access it via `_worker`)
- [x] In `send()` and `trigger()`, store the task in the set and add a `done_callback` to discard it
- [x] On `Worker.stop()`, await or cancel remaining background tasks in the set

### 4. `TaskHandle.__call__` breaks inside running event loops
`asyncio.run(coro)` creates a new event loop. Fails in pytest-asyncio, Jupyter, or when called from inside another task.

- [x] Detect whether an event loop is already running via `asyncio.get_running_loop()`
- [x] If running: use `asyncio.ensure_future()` or raise a clear error pointing to `await submit()`/`await wait()`
- [x] If not running: keep existing `asyncio.run()` behavior
- [ ] Add tests for both paths

### 5. Raw status strings instead of enums
`finish(job, "complete")` and `finish(job, "failed")` use string literals. `JobStatus` enum exists but isn't used at these call sites.

- [x] Replace `"complete"` / `"failed"` / `"cancelled"` string literals with `JobStatus.COMPLETE` etc. in `job_processor.py`
- [x] Update `BaseQueue.finish()` signature to accept `JobStatus` instead of `str`
- [x] Update `RedisQueue.finish()` and any other implementations
- [x] Audit all call sites for raw status strings

### 6. `ContextVar` propagation requires Python 3.12+
`loop.run_in_executor()` only copies context to threads in Python 3.12+. Older versions silently break `get_current_context()` in sync tasks.

- [x] Decide minimum Python version and document it
- [x] If supporting < 3.12: manually copy context using `contextvars.copy_context().run()` wrapper around the sync function in `_call_function`
- [x] If 3.12+ only: add `python_requires >= 3.12` to pyproject.toml and document

### 7. `initialize()` / `start()` coupling is error-prone
`start()` asserts `_queue_backend is not None`, meaning `initialize()` must be called first. Direct SDK users get opaque `AssertionError`.

- [x] Have `start()` call `initialize()` internally if `_queue_backend` is None
- [x] Or replace the assert with a descriptive `RuntimeError` message
- [x] Document the lifecycle in the Worker docstring

---

## Next

### Task DAG (done — implicit via parent_id)
`@worker.pipeline()` removed. Tasks calling other tasks via `submit()`/`wait()` automatically set `parent_id`, forming an implicit DAG. Use `asyncio.gather` for fan-out/fan-in.

- [x] Auto-set `parent_id` in `submit()` via `get_current_context()`
- [x] Remove `@worker.pipeline()` decorator, `PipelineDefinition`, `PipelineRun`, `PipelineResult`, `PipelineStatus`
- [x] Update examples and web UI

### Rate limiting
No per-task rate limiting exists. Production workloads need this to protect downstream services.

- [ ] Add `rate_limit` parameter to `@worker.task()` (e.g., `rate_limit="100/m"`, `rate_limit="10/s"`)
- [ ] Parse rate limit string into (count, window_seconds)
- [ ] Implement token bucket or sliding window in Redis (Lua script for atomicity)
- [ ] When rate limited, delay the job re-enqueue rather than busy-looping
- [ ] Add `rate_limit` to `TaskDefinition` and wire through `JobProcessor`
- [ ] Consider per-worker vs global (across all workers) rate limiting

### Middleware / global hooks
Hooks are currently per-task only. No way to add cross-cutting concerns globally.

- [ ] Add `Worker.middleware(before=..., after=..., on_error=...)` registration
- [ ] Define middleware protocol: `async def my_middleware(ctx, next)` (onion model like Koa/Express)
- [ ] Or simpler: `Worker.on_task_start(hook)`, `Worker.on_task_success(hook)`, etc. at worker level
- [ ] Middleware runs for ALL tasks, wrapping per-task hooks
- [ ] Common use cases: structured logging, tracing/OpenTelemetry spans, metrics emission, error reporting (Sentry)
- [ ] Allow ordering / priority of middleware

---

## Considerations

### Task routing
Currently every worker that registers a function competes for all jobs of that function. No way to route tasks to specific queues or worker pools.

- Named queues per task: `@worker.task(queue="high-priority")` or `@worker.task(queue="gpu")`
- Workers subscribe to specific queues: `Worker("gpu-worker", queues=["gpu", "default"])`
- Redis Streams already namespace by function name, so this could be an additional routing layer on top
- Consider: is function-name-based routing sufficient for current use cases?

### Broker abstraction
Currently Redis-only. Celery's multi-broker support (RabbitMQ, SQS, Redis) is one of its biggest selling points.

- `BaseQueue` already provides the abstraction layer - adding a new broker means implementing ~6 methods
- Realistic candidates: SQS (AWS-native teams), PostgreSQL SKIP LOCKED (no extra infra), NATS JetStream
- RabbitMQ is likely not worth it - if someone needs AMQP they'll use Celery
- Cost of abstraction: lowest-common-denominator API, can't use Redis-specific features (Streams, Lua)
- Recommendation: stay Redis-only for now, keep `BaseQueue` clean as an escape hatch

### Result backend abstraction
Results currently live in Redis with TTL. Celery supports Postgres, S3, MongoDB, etc.

- For short-lived results (task coordination, `wait()`): Redis is fine and fast
- For audit/history: results should flow through StatusPublisher to the Conduit API backend, which can persist anywhere
- Consider whether `queue.get_job()` (Redis) and historical result lookup (API/DB) should be separate concerns
- Probably not worth abstracting until there's a specific need for non-Redis result storage
