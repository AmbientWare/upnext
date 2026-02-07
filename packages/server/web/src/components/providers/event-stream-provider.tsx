import { useCallback, useRef, type ReactNode } from "react";
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
        status: "active",
        worker_id: event.worker_id ?? null,
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
  if (!old) return old;

  const index = old.jobs.findIndex((j) => j.id === patch.id);
  if (index < 0) return old;

  const updated = [...old.jobs];
  updated[index] = { ...updated[index], ...patch };
  return { ...old, jobs: updated };
}

/** Insert a new job into matching job list caches only. */
function insertNewJob(
  queryClient: QueryClient,
  patch: Partial<Job> & { id: string }
) {
  const queries = queryClient.getQueryCache().findAll({ queryKey: ["jobs"] });

  for (const query of queries) {
    const params = query.queryKey[1] as GetJobsParams | undefined;

    // Skip non-job-list queries (e.g. ["jobs", "stats", ...] or ["jobs", "trends", ...])
    if (typeof params === "string") continue;

    // If filtered by function, only insert if it matches
    if (params?.function && params.function !== patch.function) continue;

    queryClient.setQueryData<JobListResponse>(query.queryKey, (old) => {
      if (!old) return old;
      // Don't insert duplicates
      if (old.jobs.some((j) => j.id === patch.id)) return old;

      const newJob: Job = {
        id: patch.id,
        function: patch.function ?? "",
        status: "active",
        created_at: patch.created_at ?? null,
        scheduled_at: null,
        started_at: patch.started_at ?? null,
        completed_at: null,
        attempts: patch.attempts ?? 1,
        max_retries: patch.max_retries ?? 0,
        timeout: null,
        worker_id: patch.worker_id ?? null,
        progress: 0,
        kwargs: {},
        metadata: {},
        result: null,
        error: null,
        duration_ms: null,
      };
      return { ...old, jobs: [newJob, ...old.jobs], total: old.total + 1 };
    });
  }
}

export function EventStreamProvider({ children }: EventStreamProviderProps) {
  const queryClient = useQueryClient();
  const lastStatsInvalidation = useRef(0);

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

      const patch = jobPatchFromEvent(payload);
      if (!patch?.id) return;
      const patchWithId = patch as Partial<Job> & { id: string };

      if (payload.type === "job.started") {
        // New job — insert only into caches whose function filter matches
        insertNewJob(queryClient, patchWithId);
      } else {
        // Update existing job across all job list caches
        queryClient.setQueriesData<JobListResponse>(
          { queryKey: ["jobs"] },
          (old) => patchExistingJob(old, patchWithId)
        );
      }

      // State-change events: throttled stats + function invalidation
      if (STATE_CHANGE_EVENTS.has(payload.type)) {
        const now = Date.now();
        if (now - lastStatsInvalidation.current > STATS_THROTTLE_MS) {
          lastStatsInvalidation.current = now;
          queryClient.invalidateQueries({ queryKey: queryKeys.dashboardStats });
        }

        if (payload.function) {
          queryClient.invalidateQueries({
            queryKey: queryKeys.function(payload.function),
          });
        }
      }
    },
    [queryClient]
  );

  useEventSource(EVENT_STREAM_URL, {
    onMessage: handleMessage,
  });

  return <>{children}</>;
}
