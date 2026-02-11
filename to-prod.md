# To Prod Checklist (No Auth Scope)

Use this as the execution checklist to reach production-grade competitiveness with Celery/Prefect-style expectations.

## 1) Recovery Guarantees

- [x] Define and document execution guarantees.
  - How: write one short contract for enqueue/dequeue/retry/cancel semantics (`at least once`, duplicate possibilities, terminal state rules).
  - Done: docs are published and tests assert the documented behavior.

- [x] Enforce idempotency strategy at platform boundaries.
  - How: require stable idempotency key support for externally-triggered jobs and preserve dedupe state across retries/restarts.
  - Done: duplicate submissions with same key are rejected or coalesced predictably.

- [ ] Add crash-recovery scenarios for active jobs.
  - How: integration tests that kill workers mid-run and verify reclaim/retry/cancel behavior.
  - Done: no lost jobs; behavior is deterministic and asserted in CI.

- [ ] Add dead-letter strategy for poison jobs.
  - How: after max retries, move failed payloads to DLQ stream/set with reason and timestamps.
  - Done: operators can inspect and replay DLQ jobs safely.

## 2) Rate Limiting + Fairness

- [ ] Make `rate_limit` executable, not metadata-only.
  - How: parse and validate configured limits, then enforce with Redis token-bucket/leaky-bucket logic during dispatch.
  - Done: throughput respects configured limits under load tests.

- [ ] Add per-function concurrency caps.
  - How: maintain active-count guards per function key; dequeue only when under cap.
  - Done: hot functions cannot exceed configured concurrent runs.

- [ ] Prevent queue starvation.
  - How: schedule dequeue fairly (round-robin/weighted rotation) instead of always favoring hottest streams.
  - Done: low-volume queues continue to make progress under high-volume contention.

- [ ] Add per-tenant/per-group controls (if multi-tenant).
  - How: optional namespace or routing group quotas and limits.
  - Done: one tenant/workload cannot monopolize shared capacity.

## 3) Scheduling Durability

- [ ] Persist scheduler progress explicitly.
  - How: track last successful run cursor per cron/function in durable store.
  - Done: restart does not lose schedule state.

- [ ] Add startup reconciliation for missed runs.
  - How: on boot, compare expected schedule windows with persisted cursor and backfill per policy.
  - Done: missed windows are either replayed or intentionally skipped with reason.

- [ ] Add missed-run policy controls.
  - How: per-cron policy (`catch_up`, `latest_only`, `skip`) and max catch-up window.
  - Done: behavior is configurable and test-covered.

- [ ] Protect against double-scheduling.
  - How: atomic schedule reservation per function+window.
  - Done: no duplicate cron emissions for same window in failover races.

## 4) Operational Observability

- [ ] Expose queue lag and wait-time by function.
  - How: record enqueue->start delay histograms and queued depth per function.
  - Done: dashboard shows lag, p95 wait, and backlog hotspots.

- [ ] Expose dispatch reason codes.
  - How: emit structured reasons (`paused`, `rate_limited`, `no_capacity`, `cancelled`, `retrying`) in events/metrics.
  - Done: operators can explain why jobs are not running.

- [ ] Add failure/latency alert hooks.
  - How: configurable thresholds + webhook/notification integration points.
  - Done: alert fires on sustained error rate/latency/lag violations.

- [ ] Add runbook-oriented dashboard views.
  - How: include “top failing functions”, “oldest queued”, “stuck active jobs”.
  - Done: on-call can triage incidents without querying raw Redis/DB.

## 5) Workflow Primitives

- [ ] Strengthen parent/child execution state model.
  - How: explicitly track tree status from child completions and propagate terminal outcomes correctly.
  - Done: parent status is correct across mixed success/failure/cancel states.

- [ ] Add selective rerun for failed children.
  - How: rerun only failed leaf/branch jobs without replaying successful siblings.
  - Done: operators can recover partial failures cheaply.

- [ ] Add dependency-aware scheduling hooks.
  - How: optional “run-after” guards for child tasks and branch conditions.
  - Done: simple DAG-style workflows are supported without custom user orchestration code.

- [ ] Add workflow-level timeout and cancellation propagation.
  - How: enforce root-level timeout/cancel signals cascading through descendants.
  - Done: canceling root reliably stops or marks descendants.

## 6) Hardening + Release Gates

- [ ] Load test throughput and fairness before release.
  - How: benchmark mixed workloads (hot + cold queues, retries, cron, events) with target concurrency.
  - Done: publish baseline throughput, p95 latency, and resource usage.

- [ ] Run chaos/failure drills.
  - How: kill workers/Redis connections during peak load and verify recovery objectives.
  - Done: documented RTO/RPO behavior is met.

- [ ] Add migration/versioning policy for queue/job schemas.
  - How: version payload schema and validate compatibility in deploy pipeline.
  - Done: safe rolling deploys with no stuck jobs from schema drift.

- [ ] Publish operator runbooks.
  - How: include incident steps for backlog growth, stuck jobs, retry storms, and scheduler drift.
  - Done: on-call docs are complete and linked from dashboard/docs.

- [ ] Define merge-to-prod quality gate.
  - How: require passing server/sdk/web tests, lint, build, and key integration checks.
  - Done: CI blocks promotion unless all gates pass.
