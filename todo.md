# UpNext — Production Readiness TODO

Work through these items to get UpNext production-ready. Organized by priority and grouped by package.

---

## Critical — Database & Data Integrity

- [ ] Add compound index on `(function, status)` for dashboard queries
- [ ] Add index on `root_id` for job tree traversal (`list_job_subtree`)
- [ ] Add index on `(created_at, status)` for trend aggregation
- [ ] Enforce `status` as a proper ENUM or CHECK constraint (currently `String(20)`, accepts any value)
- [ ] Add FK constraint on `parent_id` → `job_history.id` for parent/child relationships
- [ ] Implement cursor-based pagination (current `LIMIT+1` approach won't scale)
- [ ] Add Alembic migrations for all schema changes (currently single initial migration)
- [ ] Add garbage collection for orphaned `pending_artifacts` older than retention window

---

## Critical — Error Handling & Validation

- [ ] Standardize error response envelope across all API endpoints (consistent shape for 4xx/5xx)
- [ ] Validate `status` query parameter values against allowed enum set (currently accepts `status=foo`)
- [ ] Fix inconsistent DB-unavailable behavior (some endpoints return empty results, others return 503)
- [ ] Add React error boundaries to prevent full-app crashes on unhandled errors
- [ ] Add explicit SSE error events on Redis disconnection (currently streams end silently)
- [ ] Add input sanitization for function names, job IDs, artifact names
- [ ] Add artifact upload size limits and streaming for large files (currently buffers entire content in memory)

---

## High — Queue & Worker Reliability

- [ ] Add `_stream_claims` cache cleanup (evict entries every 10k jobs or 1 hour to prevent memory leak)
- [ ] Log warnings when status publisher buffer reaches 90% capacity
- [ ] Add background consumer group cleanup (scan + `XGROUP DESTROY` for stale groups)
- [ ] Implement IPC mechanism for process pool cancellation (e.g., `multiprocessing.Event`)
- [ ] Add monitoring metrics: status buffer fullness, stream claims cache size, claim timeout hits
- [ ] Add configurable overflow strategy for status buffer (currently silently drops events)
- [ ] Fix sweep lock contention — consider per-function sweep or sharded sweep locks

---

## High — API & Server Hardening

- [ ] Add request rate limiting / throttling on API endpoints
- [ ] Add SSE connection limits and backpressure handling (currently unbounded)
- [ ] Fix snapshot cache — use TTL-based cleanup instead of size-based all-or-nothing flush at 256
- [ ] Add request correlation IDs for distributed tracing
- [ ] Replace global singleton pattern for Redis/DB with explicit lifecycle management and circuit breaker
- [ ] Fix consumer group startup — `xgroup_create(id="0")` replays entire stream history on first boot
- [ ] Add structured JSON logging for production (ECS/Splunk compatible)

---

## Medium — SDK Improvements

- [ ] Make progress coalescing thresholds configurable (currently hardcoded 0.01 delta, 0.2s interval)
- [ ] Add `TaskTimeoutError` subclass to distinguish timeouts from execution failures
- [ ] Document cron catch-up semantics and `MissedRunPolicy` behavior
- [ ] Document callback signatures (`on_start`, `on_failure`, `on_retry`, `on_complete`) with examples
- [ ] Document rate limiting, routing groups, and `group_max_concurrency` with examples
- [ ] Document idempotency key normalization strategy
- [ ] Add `context.record_metric()` for custom metrics
- [ ] Add `context.tags` for structured logging metadata

---

## Medium — Queue Features

- [ ] Add priority queue support (bypass fair round-robin for high-priority jobs)
- [ ] Add CLI tool for manual DLQ management (list, replay, purge dead letter entries)
- [ ] Add rate limiting at enqueue time (currently only checked at dequeue — jobs still enter queue)
- [ ] Validate progress is monotonically increasing (currently allows regression e.g. 0.8 → 0.5)

---

## Medium — Dashboard Improvements

- [ ] Add virtualization for large job timelines (tree rendering)
- [ ] Memoize expensive computations with `useMemo`/`useCallback` more consistently
- [ ] Add code splitting for dashboard panels (lazy load heavy views)
- [ ] Upgrade ESLint to `strict` TypeScript rules
- [ ] Add comprehensive test coverage for `EventStreamProvider` state logic
- [ ] Add integration tests for real-time SSE updates

---

## Medium — Observability & Monitoring

- [ ] Add OpenTelemetry integration — automatic span creation for task execution
- [ ] Add trace context propagation through parent/child task chains
- [ ] Expose queue depth metrics per function (for external monitoring)
- [ ] Add worker health check HTTP endpoint
- [ ] Add alert on high invalid event rate (events written to dead-letter stream)

---

## Low — Operational Polish

- [ ] Extract magic numbers to named constants (0.75s cache TTL, 256 cache size, 15s stream timeout)
- [ ] Refactor streaming endpoints — extract common SSE pattern to shared factory/mixin
- [ ] Add pagination links (next, previous) to list responses
- [ ] Clean up repetitive code across `jobs_stream.py`, `workers_stream.py`, `artifacts_stream.py`
- [ ] Add structured comments/docstrings on complex logic (event batching, tree building, coalescing)
- [ ] Add configuration validation — warn on invalid environment variable values

---

## Low — Future Considerations

- [ ] Job dependency DAGs (wait for upstream tasks before executing)
- [ ] Pluggable queue backend interface (PostgreSQL, DynamoDB alternatives)
- [ ] Dynamic cron job management (add/remove/pause schedules at runtime via API)
- [ ] Checkpoint schema versioning for safe deserialization across deploys
- [ ] i18n support for dashboard
- [ ] Competitive documentation page — "Why UpNext over Celery/Dramatiq/Prefect" with code comparisons
