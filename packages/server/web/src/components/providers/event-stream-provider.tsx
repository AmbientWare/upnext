import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { queryKeys, type GetJobsParams } from "@/lib/conduit-api";
import { useEventSource } from "@/hooks/use-event-source";
import type { Job, JobListResponse } from "@/lib/types";

interface EventStreamProviderProps {
  children: ReactNode;
}

const EVENT_STREAM_URL = "/api/v1/events/stream";

/** Minimum interval between dashboard stats refetches (ms). */
const STATS_THROTTLE_MS = 5_000;
/** Minimum interval between function detail refetches triggered by SSE (ms). */
const FUNCTION_THROTTLE_MS = 3_000;
/** Apply streamed events with a tiny delay for stable, ordered UI updates. */
const EVENT_STEP_MS = 40;
/** Use a faster cadence when backlog grows to avoid UI lag. */
const EVENT_BURST_STEP_MS = 8;
/** Backlog level considered a burst. */
const BURST_QUEUE_THRESHOLD = 50;
/** Hard cap for queued stream events to avoid unbounded memory growth. */
const MAX_QUEUE_LENGTH = 2_000;

/** Event types that change aggregate counts and warrant a stats refetch. */
const STATE_CHANGE_EVENTS = new Set([
  "job.started",
  "job.completed",
  "job.failed",
  "job.retrying",
]);

interface JobEvent {
  type: string;
  job_id?: string;
  worker_id?: string;
  function?: string;
  function_name?: string;
  parent_id?: string;
  root_id?: string;
  attempt?: number;
  max_retries?: number;
  started_at?: string;
  duration_ms?: number;
  completed_at?: string;
  error?: string;
  failed_at?: string;
  current_attempt?: number;
  next_attempt?: number;
  progress?: number;
  message?: string;
}

/** Build a partial Job update from the streamed event. */
function jobPatchFromEvent(event: JobEvent): Partial<Job> | null {
  const { type, job_id } = event;
  if (!job_id) return null;

  switch (type) {
    case "job.started":
      return {
        id: job_id,
        function: event.function ?? "",
        function_name: event.function_name ?? event.function ?? "",
        status: "active",
        worker_id: event.worker_id ?? null,
        parent_id: event.parent_id ?? null,
        root_id: event.root_id ?? job_id,
        attempts: event.attempt ?? 1,
        max_retries: event.max_retries ?? 0,
        started_at: event.started_at ?? null,
        created_at: event.started_at ?? null,
        progress: 0,
        error: null,
        result: null,
        completed_at: null,
        duration_ms: null,
      };
    case "job.completed":
      return {
        id: job_id,
        status: "complete",
        duration_ms: event.duration_ms ?? null,
        completed_at: event.completed_at ?? null,
        progress: 1,
      };
    case "job.failed":
      return {
        id: job_id,
        status: "failed",
        error: event.error ?? null,
        completed_at: event.failed_at ?? null,
      };
    case "job.retrying":
      return {
        id: job_id,
        status: "retrying",
        attempts: event.current_attempt ?? 1,
        error: event.error ?? null,
      };
    case "job.progress":
      return {
        id: job_id,
        progress: event.progress ?? 0,
      };
    default:
      return null;
  }
}

/** Update an existing job in a job list. Returns undefined if not found. */
function patchExistingJob(
  old: JobListResponse | undefined,
  patch: Partial<Job> & { id: string }
): JobListResponse | undefined {
  if (!old || !Array.isArray(old.jobs)) return old;

  const index = old.jobs.findIndex((j) => j.id === patch.id);
  if (index < 0) return old;

  const updated = [...old.jobs];
  updated[index] = { ...updated[index], ...patch };
  return { ...old, jobs: updated };
}

function createJobFromPatch(patch: Partial<Job> & { id: string }): Job {
  return {
    id: patch.id,
    function: patch.function ?? "",
    function_name: patch.function_name ?? patch.function ?? "",
    status: "active",
    created_at: patch.created_at ?? null,
    scheduled_at: null,
    started_at: patch.started_at ?? null,
    completed_at: null,
    attempts: patch.attempts ?? 1,
    max_retries: patch.max_retries ?? 0,
    timeout: null,
    worker_id: patch.worker_id ?? null,
    parent_id: patch.parent_id ?? null,
    root_id: patch.root_id ?? patch.id,
    progress: 0,
    kwargs: {},
    metadata: patch.metadata ?? {},
    result: null,
    error: null,
    duration_ms: null,
  };
}

/** Iterate all cached job-list queries (excluding jobs stats/trends queries). */
function forEachJobsListQuery(
  queryClient: QueryClient,
  callback: (queryKey: readonly unknown[], params: GetJobsParams | undefined) => void
) {
  const queries = queryClient.getQueryCache().findAll({ queryKey: ["jobs"] });

  for (const query of queries) {
    const params = query.queryKey[1] as GetJobsParams | string | undefined;

    // Skip non-job-list queries (e.g. ["jobs", "stats", ...] or ["jobs", "trends", ...])
    if (typeof params === "string") continue;

    callback(query.queryKey, params);
  }
}

/** Update existing jobs in matching job-list caches only. */
function updateExistingJob(
  queryClient: QueryClient,
  patch: Partial<Job> & { id: string }
) {
  forEachJobsListQuery(queryClient, (queryKey) => {
    queryClient.setQueryData<JobListResponse>(queryKey, (old) =>
      patchExistingJob(old, patch)
    );
  });
}

/** Insert a new job into matching job list caches only. */
function insertNewJob(
  queryClient: QueryClient,
  patch: Partial<Job> & { id: string }
) {
  forEachJobsListQuery(queryClient, (queryKey, params) => {
    // If filtered by function, only insert if it matches
    if (params?.function && params.function !== patch.function) return;

    queryClient.setQueryData<JobListResponse>(queryKey, (old) => {
      if (!old) return old;
      // Don't insert duplicates
      if (old.jobs.some((j) => j.id === patch.id)) return old;
      const newJob = createJobFromPatch(patch);
      return { ...old, jobs: [newJob, ...old.jobs], total: old.total + 1 };
    });
  });
}

function updateJobDetailCache(
  queryClient: QueryClient,
  patch: Partial<Job> & { id: string }
) {
  queryClient.setQueryData<Job>(queryKeys.job(patch.id), (old) => {
    if (!old) return old;
    return { ...old, ...patch };
  });
}

function upsertTimelineJob(
  old: JobListResponse | undefined,
  patch: Partial<Job> & { id: string },
  payload: JobEvent,
  rootJobId: string
): JobListResponse | undefined {
  if (!old) return old;

  const index = old.jobs.findIndex((j) => j.id === patch.id);
  if (index >= 0) {
    const updated = [...old.jobs];
    updated[index] = { ...updated[index], ...patch };
    return { ...old, jobs: updated };
  }

  if (payload.type !== "job.started") return old;

  const payloadRootId = payload.root_id ?? patch.root_id ?? patch.id;
  const matchesRoot = payloadRootId === rootJobId;
  const hasParentInTree = !!payload.parent_id && old.jobs.some((j) => j.id === payload.parent_id);
  const isRoot = patch.id === rootJobId;
  if (!matchesRoot && !hasParentInTree && !isRoot) return old;

  const newJob = createJobFromPatch(patch);
  return { ...old, jobs: [...old.jobs, newJob], total: old.total + 1 };
}

function updateTimelineCaches(
  queryClient: QueryClient,
  patch: Partial<Job> & { id: string },
  payload: JobEvent
) {
  const queries = queryClient.getQueryCache().findAll({
    queryKey: ["jobs", "timeline"],
  });

  for (const query of queries) {
    const rootJobId = query.queryKey[2];
    if (typeof rootJobId !== "string") continue;
    queryClient.setQueryData<JobListResponse>(query.queryKey, (old) =>
      upsertTimelineJob(old, patch, payload, rootJobId)
    );
  }
}

export function EventStreamProvider({ children }: EventStreamProviderProps) {
  const queryClient = useQueryClient();
  const lastStatsInvalidation = useRef(0);
  const lastFunctionInvalidation = useRef<Record<string, number>>({});
  const eventQueue = useRef<JobEvent[]>([]);
  const eventTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applyStreamEvent = useCallback(
    (payload: JobEvent) => {
      const patch = jobPatchFromEvent(payload);
      if (!patch?.id) return;
      const patchWithId = patch as Partial<Job> & { id: string };

      if (payload.type === "job.started") {
        // New job — insert only into caches whose function filter matches
        insertNewJob(queryClient, patchWithId);
      } else {
        // Update existing job across matching job-list caches only
        updateExistingJob(queryClient, patchWithId);
      }
      updateJobDetailCache(queryClient, patchWithId);
      updateTimelineCaches(queryClient, patchWithId, payload);

      // State-change events: throttled stats + function invalidation
      if (STATE_CHANGE_EVENTS.has(payload.type)) {
        const now = Date.now();
        if (now - lastStatsInvalidation.current > STATS_THROTTLE_MS) {
          lastStatsInvalidation.current = now;
          queryClient.invalidateQueries({ queryKey: queryKeys.dashboardStats });
        }

        if (payload.function) {
          const lastByFunction = lastFunctionInvalidation.current;
          const previous = lastByFunction[payload.function] ?? 0;
          if (now - previous > FUNCTION_THROTTLE_MS) {
            lastByFunction[payload.function] = now;
            queryClient.invalidateQueries({
              queryKey: queryKeys.function(payload.function),
            });
          }
        }
      }
    },
    [queryClient]
  );

  const drainQueue = useCallback(function drainQueueImpl() {
    eventTimer.current = null;
    if (eventQueue.current.length === 0) return;

    const batchSize =
      eventQueue.current.length > BURST_QUEUE_THRESHOLD ? 8 : 1;
    for (let i = 0; i < batchSize; i += 1) {
      const next = eventQueue.current.shift();
      if (!next) break;
      applyStreamEvent(next);
    }

    if (eventQueue.current.length > 0) {
      const delay =
        eventQueue.current.length > BURST_QUEUE_THRESHOLD
          ? EVENT_BURST_STEP_MS
          : EVENT_STEP_MS;
      eventTimer.current = setTimeout(drainQueueImpl, delay);
    }
  }, [applyStreamEvent]);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data) return;

      let payload: JobEvent;
      try {
        payload = JSON.parse(event.data);
        if (!payload?.type || !payload?.job_id) return;
      } catch {
        return;
      }

      // Keep only the latest queued progress event per job.
      if (payload.type === "job.progress") {
        for (let i = eventQueue.current.length - 1; i >= 0; i -= 1) {
          const queued = eventQueue.current[i];
          if (queued.job_id !== payload.job_id) continue;
          if (queued.type === "job.progress") {
            eventQueue.current[i] = payload;
            if (!eventTimer.current) {
              eventTimer.current = setTimeout(drainQueue, 0);
            }
            return;
          }
          break;
        }
      }

      eventQueue.current.push(payload);
      if (eventQueue.current.length > MAX_QUEUE_LENGTH) {
        const dropIndex = eventQueue.current.findIndex(
          (queued) => queued.type === "job.progress"
        );
        if (dropIndex >= 0) {
          eventQueue.current.splice(dropIndex, 1);
        } else {
          eventQueue.current.shift();
        }
      }
      if (!eventTimer.current) {
        eventTimer.current = setTimeout(drainQueue, 0);
      }
    },
    [drainQueue]
  );

  useEffect(() => {
    return () => {
      if (eventTimer.current) {
        clearTimeout(eventTimer.current);
        eventTimer.current = null;
      }
      eventQueue.current = [];
    };
  }, []);

  useEventSource(EVENT_STREAM_URL, {
    onMessage: handleMessage,
  });

  return <>{children}</>;
}
