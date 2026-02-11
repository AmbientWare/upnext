# Next Steps: Stream Simplification + Production Readiness

## Goal
Reduce unnecessary live connections, make "Live" behavior predictable, and harden realtime behavior for production.

## Current Issues (Observed)
- 4 global SSE streams stay open on every page.
- Several pages open additional SSE streams on top of global streams.
- Duplicate data paths (SSE + polling + cache invalidations) increase complexity.
- "Live off" can appear inconsistent when global streams still mutate caches.
- Reconnect/backoff behavior is decentralized and hard to reason about end-to-end.

## Target Architecture
- Route-scoped streaming by default.
- Only one stream per concern, mounted where needed.
- "Live" strictly controls whether realtime updates are applied.
- Polling retained only as a safety resync (long interval) or non-live fallback.
- Unified stream manager for connection state, backoff, and observability.

## Phased Plan (Checklist)

### Phase 1: Inventory + Contracts
- [x] Document every streaming endpoint and owning page/component.
- [x] Define per-view data contract: live mode, window mode, and refresh expectations.
- [x] Decide which data (if any) is truly global and justify it.
- [x] Add explicit API behavior notes for streams (snapshot cadence, reconnect expectations).

### Phase 2: Stream Topology Simplification
- [x] Remove always-on global stream subscriptions from root provider.
- [x] Replace with route-scoped providers/hooks for dashboard, APIs, workers, jobs, functions.
- [x] Ensure each stream is mounted once per route tree (no duplicate listeners).
- [x] Gate all route streams with explicit `enabled` and visibility checks.

### Phase 3: Live/Window Semantics
- [x] Standardize behavior:
  - Live mode: show latest 50, realtime on.
  - Window mode: realtime off, show query-returned set.
- [x] Ensure toggling `Live -> Off` stops all realtime mutation for that panel.
- [x] Keep time-window controls consistent across pages and sizes.
- [x] Align query keys to avoid cross-mode cache contamination.

### Phase 4: Reliability + Failure Handling
- [x] Centralize SSE lifecycle in one utility/service:
  - reconnect with jittered exponential backoff
  - connection state (`connecting/open/reconnecting/closed`)
  - heartbeat/idle detection
- [x] Normalize 404/503 stream failure handling and user-visible fallback states.
- [x] Add automatic downgrade path (stream unavailable -> polling fallback).
- [x] Add resync-on-reconnect strategy with per-query throttling.

### Phase 5: Performance + Resource Controls
- [x] Cap in-memory event queues and dedupe aggressively by entity ID/type.
- [x] Stop processing updates for hidden/inactive tabs where possible.
- [x] Add lightweight rate limits for cache invalidation and redraw-heavy updates.
- [ ] Validate browser tab load with multiple open tabs.

### Phase 6: Testing + Observability
- [x] Add tests for route precedence and static vs dynamic stream paths.
- [x] Add tests for live toggle correctness (no updates in window mode).
- [x] Add tests for reconnect, fallback, and cache isolation across modes.
- [x] Add frontend metrics/logs:
  - active stream count
  - reconnect attempts
  - dropped events / queue overflow
  - stream uptime

### Phase 7: Rollout + Cleanup
- [ ] Feature-flag new stream topology for safe rollout.
- [ ] Run side-by-side verification in dev/staging.
- [ ] Remove deprecated stream code paths and dead config flags.
- [ ] Update docs for realtime model and troubleshooting.

## Acceptance Criteria
- No unnecessary always-on streams when route is not mounted.
- Live/off behavior is deterministic across dashboard, APIs, workers, functions, and jobs.
- No route collisions for `/stream` endpoints.
- Stream downtime gracefully degrades to polling without broken UI.
- Realtime views remain responsive under sustained load.

## Suggested Execution Order
1. Phase 1 + Phase 2 (topology cleanup)
2. Phase 3 (live/window correctness)
3. Phase 4 (resilience)
4. Phase 5 + Phase 6 (hardening)
5. Phase 7 (rollout + cleanup)
