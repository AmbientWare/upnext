# Conduit UI Polish — Task List

## Polling & Data Freshness

- [ ] **Disable polling on hidden tabs**
  Set `refetchIntervalInBackground: false` in the global QueryClient config in `main.tsx`.
  Currently every open tab polls the server even when the user isn't looking at it.
  Single line change, immediate reduction in unnecessary server load.

- [ ] **SSE for job events**
  Add a Server-Sent Events endpoint (`GET /api/v1/events/stream`) that the `StreamSubscriber`
  publishes to via Redis Pub/Sub when it processes job events. On the frontend, create a
  lightweight `useEventSource` hook that calls `queryClient.invalidateQueries()` for the
  relevant query keys (`jobs`, `dashboardStats`) when events arrive. Keep existing
  `refetchInterval` as a fallback but relax intervals to 30-60s. This gives near-instant
  job status updates without replacing the polling infrastructure.
  - Backend: new SSE route + Pub/Sub publish in `stream_subscriber.py`
  - Frontend: `useEventSource` hook + invalidation mapping in a shared provider

## Loading States

- [ ] **Skeleton loading screens for all pages**
  Every page currently shows blank space while initial data loads. Add skeleton placeholder
  components that match the layout of the real content (table rows, metric cards, chart areas).
  Use pulsing placeholder blocks with `animate-pulse` — no library needed.
  - `routes/dashboard/index.tsx` — skeleton for overview metrics grid, trends panels, jobs table
  - `routes/workers/index.tsx` — skeleton for worker table rows
  - `routes/functions/index.tsx` — skeleton for function table rows
  - `routes/functions/$name/index.tsx` — replace "Loading..." text with skeleton for metrics + jobs table
  - `routes/apis/index.tsx` — skeleton for API table rows
  - Check `isPending` from `useQuery` to toggle between skeleton and real content

## Animated Counters

- [ ] **Create `useAnimatedNumber` hook**
  Build a small hook that smoothly interpolates between the previous and next numeric value
  using `requestAnimationFrame`. Should handle integers, decimals, and formatted strings
  (e.g. "12.4K", "98.2%"). Duration ~400-600ms with an ease-out curve. No external library.
  Place in `web/src/hooks/use-animated-number.ts`.

- [ ] **Apply animated counters to dashboard metrics**
  Wire `useAnimatedNumber` into the system overview panel (`system-overview-panel.tsx`):
  workers count, throughput, active jobs, success rate, API req/min, latency, error rate.
  These are the most visible numbers and update every 10s — smooth transitions here have
  the highest visual impact.

- [ ] **Apply animated counters to function detail metrics**
  Wire into the function detail page (`functions/$name/index.tsx`) and `metric-card.tsx`:
  runs, success rate, avg duration, p95 duration.

- [ ] **Apply animated counters to API summary stats**
  Wire into the APIs page (`apis/index.tsx`): total req/min, avg latency header stats.

## List & Table Animations

- [ ] **Add subtle row enter/exit animations to tables**
  When data refreshes and rows appear, disappear, or reorder, animate the transition.
  Use a lightweight approach — either `@formkit/auto-animate` (one-line integration per
  table body) or CSS `@starting-style` + `transition` for enter animations.
  Apply to:
  - `components/shared/jobs-table.tsx` — job rows (most dynamic, updates every 5s)
  - `routes/workers/index.tsx` — worker rows
  - `routes/functions/index.tsx` — function rows
  - `routes/apis/index.tsx` — API rows
  Keep animations fast (150-200ms) so they feel responsive, not sluggish.

## Error Handling

- [ ] **Add toast notification system**
  Add a toast/notification component for surfacing errors and confirmations. Use the Radix UI
  Toast primitive (already using Radix for other components) or `sonner` (lightweight,
  ~3KB). Wire into TanStack Query's global `onError` callback in the QueryClient config
  so failed requests automatically surface a toast like "Failed to load workers".
  Also use for action confirmations (e.g. "Job cancelled", "Job retried").

## Chart Polish

- [ ] **Configure chart animations on data change**
  Recharts `<Bar>` components in the three trend panels currently use default animation
  behavior. Explicitly set `animationDuration={300}` and `animationEasing="ease-out"` for
  smooth transitions when chart data refreshes. Adjust in:
  - `dashboard/-components/trends-panel.tsx`
  - `dashboard/-components/api-trends-panel.tsx`
  - `functions/$name/-components/job-trends-panel.tsx`

## Empty States

- [ ] **Improve empty state designs**
  Current empty states are plain text ("No workers found"). Add a minimal illustration or
  icon, a primary message, and a helpful subtitle. For example, the workers page could show
  a server icon with "No workers connected" and "Workers will appear here when they
  register with Conduit." Keep it simple — icon + two lines of text, centered in the
  table area. Apply to:
  - `routes/workers/index.tsx`
  - `routes/functions/index.tsx`
  - `routes/apis/index.tsx`
  - `components/shared/jobs-table.tsx`
  - Trend panels (all three)

## Progress Bar

- [ ] **Tune progress bar transition timing**
  The progress bar in `components/shared/progress-bar.tsx` uses `transition-all` which
  defaults to 150ms. For job progress that updates every 5s, a longer easing
  (`transition-all duration-500 ease-out`) would feel smoother and more intentional.
  Also consider adding a subtle shimmer/stripe animation on active progress bars to
  indicate the job is still running between updates.

## Page Transitions

- [ ] **Add fade transition between routes**
  Wrap the `<Outlet />` in `__root.tsx` with a simple CSS fade transition (opacity 0→1,
  ~150ms). This smooths out navigation between dashboard, workers, functions, and APIs
  pages. Can be done with a `<Suspense>` fallback + CSS transition or a small wrapper
  component. Keep it subtle — just enough to avoid the hard cut.
