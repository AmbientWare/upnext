# Realtime Stream Inventory

## Purpose
Single source of truth for SSE endpoints, owning UI surfaces, and live/window behavior.

## Global Route-Scoped Streams
These are mounted by the root layout via `EventStreamProvider` and are enabled by route.

- `GET /api/v1/events/stream`
  - Event types: job lifecycle events (`job.started`, `job.progress`, `job.completed`, `job.failed`, `job.retrying`)
  - Consumer: `packages/server/web/src/components/providers/event-stream-provider.tsx`
  - Routes: `/dashboard`, `/functions/*`, `/jobs/*`
  - Cache targets: `jobs`, `jobs.job`, `jobs.timeline`, dashboard/function invalidations

- `GET /api/v1/apis/stream`
  - Event types: `apis.snapshot`, `api.snapshot`
  - Consumer: `packages/server/web/src/components/providers/event-stream-provider.tsx`
  - Routes: `/apis/*`
  - Cache targets: `apis`, `apis.api`

- `GET /api/v1/apis/events/stream`
  - Event types: `api.request`
  - Consumer: `packages/server/web/src/components/providers/event-stream-provider.tsx`
  - Routes: `/dashboard`, `/apis/*`
  - Cache targets: `apis.events` (live-mode keys only)

- `GET /api/v1/workers/stream`
  - Event types: `workers.snapshot`
  - Consumer: `packages/server/web/src/components/providers/event-stream-provider.tsx`
  - Routes: `/dashboard`, `/workers/*`
  - Cache targets: `workers`

## Page-Scoped Streams
These are mounted only by specific pages/components.

- `GET /api/v1/jobs/trends/stream`
  - Consumers:
    - `packages/server/web/src/routes/dashboard/-components/trends-panel.tsx`
    - `packages/server/web/src/routes/functions/$name/-components/job-trends-panel.tsx`

- `GET /api/v1/apis/trends/stream`
  - Consumer: `packages/server/web/src/routes/dashboard/-components/api-trends-panel.tsx`

- `GET /api/v1/apis/{name}/stream`
  - Consumer: `packages/server/web/src/routes/apis/$name/index.tsx`

- `GET /api/v1/jobs/{job_id}/artifacts/stream`
  - Consumer: `packages/server/web/src/routes/jobs/$jobId/-components/job-artifacts-tab.tsx`

## Live/Window Contract
- Live mode
  - Uses `LIVE_LIST_LIMIT` (`50`)
  - Uses active auto refresh (`LIVE_REFRESH_INTERVAL_MS`, `5000`) where stream-delivery is not direct
  - Receives stream-driven cache updates when key family matches live keys

- Window mode
  - Live refresh disabled (`refetchInterval: false`)
  - Uses window-specific query keys (for isolation from stream mutations)
  - Shows full server query response (no UI-side 50 cap)

## Reliability Contract
- All root-scoped streams use:
  - reconnect with jittered exponential backoff
  - optional idle timeout reconnect guard (disabled by default)
  - optional pause while tab is hidden
- On reconnect/idle, provider triggers throttled query resync invalidation.
- Fallback polling-style resync starts only after sustained stream degradation
  (grace window + interval), and stops once streams are healthy again.

## Notes
- Stream routes must be declared before dynamic `{id}` routes to avoid path capture.
- `workers/stream` precedence is enforced in `packages/server/src/server/routes/workers/__init__.py`.
