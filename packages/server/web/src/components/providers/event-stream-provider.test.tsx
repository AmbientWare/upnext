import { type ReactNode } from "react";
import { render, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { queryKeys } from "@/lib/upnext-api";
import type {
  ApiPageResponse,
  ApiRequestEventsResponse,
  ApisListResponse,
  Job,
  JobListResponse,
  WorkersListResponse,
} from "@/lib/types";
import { EventStreamProvider } from "./event-stream-provider";
import type { EventSourceConnectionState } from "@/hooks/use-event-source";

const messageHandlers = new Map<string, (event: MessageEvent) => void>();
const stateHandlers = new Map<
  string,
  (state: EventSourceConnectionState) => void
>();

vi.mock("@/hooks/use-event-source", () => ({
  useEventSource: (
    _url: string,
    options: {
      onMessage?: (event: MessageEvent) => void;
      onStateChange?: (state: EventSourceConnectionState) => void;
    }
  ) => {
    if (options.onMessage) {
      messageHandlers.set(_url, options.onMessage);
    }
    if (options.onStateChange) {
      stateHandlers.set(_url, options.onStateChange);
    }
    return { current: null };
  },
}));

function mkJob(partial: Partial<Job> & Pick<Job, "id">): Job {
  return {
    id: partial.id,
    function: partial.function ?? "fn",
    function_name: partial.function_name ?? "fn",
    job_type: partial.job_type ?? "task",
    source: partial.source ?? { type: "task" },
    status: partial.status ?? "active",
    created_at: partial.created_at ?? "2026-02-08T00:00:00Z",
    scheduled_at: partial.scheduled_at ?? null,
    started_at: partial.started_at ?? partial.created_at ?? null,
    completed_at: partial.completed_at ?? null,
    attempts: partial.attempts ?? 1,
    max_retries: partial.max_retries ?? 0,
    timeout: partial.timeout ?? null,
    worker_id: partial.worker_id ?? null,
    parent_id: partial.parent_id ?? null,
    root_id: partial.root_id ?? partial.id,
    progress: partial.progress ?? 0,
    kwargs: partial.kwargs ?? {},
    checkpoint: partial.checkpoint ?? null,
    checkpoint_at: partial.checkpoint_at ?? null,
    dlq_replayed_from: partial.dlq_replayed_from ?? null,
    dlq_failed_at: partial.dlq_failed_at ?? null,
    result: partial.result ?? null,
    error: partial.error ?? null,
    duration_ms: partial.duration_ms ?? null,
  };
}

function emptyList(): JobListResponse {
  return { jobs: [], total: 0, has_more: false };
}

function renderWithQueryClient(client: QueryClient, children: ReactNode) {
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

function getJobMessageHandler() {
  return messageHandlers.get("/api/v1/events/stream");
}

function getApiMessageHandler() {
  return messageHandlers.get("/api/v1/apis/stream");
}

function getApiRequestEventsMessageHandler() {
  return messageHandlers.get("/api/v1/apis/events/stream");
}

function getWorkersMessageHandler() {
  return messageHandlers.get("/api/v1/workers/stream");
}

function getJobStateHandler() {
  return stateHandlers.get("/api/v1/events/stream");
}

async function flushQueue() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(120);
    await Promise.resolve();
  });
}

describe("EventStreamProvider", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    messageHandlers.clear();
    stateHandlers.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("inserts job.started only into matching function-filtered job caches", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    const keyA = queryKeys.jobs({ function: "fn.a" });
    const keyB = queryKeys.jobs({ function: "fn.b" });
    client.setQueryData(keyA, emptyList());
    client.setQueryData(keyB, emptyList());

    renderWithQueryClient(client, (
      <EventStreamProvider>
        <div />
      </EventStreamProvider>
    ));

    const jobHandler = getJobMessageHandler();
    expect(jobHandler).toBeDefined();

    act(() => {
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.started",
            job_id: "job-1",
            function: "fn.a",
            function_name: "Task A",
            root_id: "job-1",
            attempt: 1,
            max_retries: 0,
            started_at: "2026-02-08T10:00:00Z",
          }),
        })
      );
    });
    await flushQueue();

    const listA = client.getQueryData<JobListResponse>(keyA);
    const listB = client.getQueryData<JobListResponse>(keyB);

    expect(listA?.jobs.map((j) => j.id)).toEqual(["job-1"]);
    expect(listB?.jobs).toEqual([]);
  });

  it("guards timeline insertion to related root/parent events", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    const timelineKey = queryKeys.jobTimeline("root-1");
    client.setQueryData(timelineKey, {
      jobs: [mkJob({ id: "root-1", root_id: "root-1", status: "active" })],
      total: 1,
      has_more: false,
    } satisfies JobListResponse);

    renderWithQueryClient(client, (
      <EventStreamProvider>
        <div />
      </EventStreamProvider>
    ));

    const jobHandler = getJobMessageHandler();

    act(() => {
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.started",
            job_id: "unrelated",
            function: "fn.x",
            function_name: "X",
            root_id: "other-root",
            parent_id: null,
            attempt: 1,
            max_retries: 0,
            started_at: "2026-02-08T10:00:00Z",
          }),
        })
      );
    });
    await flushQueue();

    let timeline = client.getQueryData<JobListResponse>(timelineKey);
    expect(timeline?.jobs.map((j) => j.id)).toEqual(["root-1"]);

    act(() => {
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.started",
            job_id: "child-1",
            function: "fn.x",
            function_name: "Child",
            root_id: "root-1",
            parent_id: "root-1",
            attempt: 1,
            max_retries: 0,
            started_at: "2026-02-08T10:00:01Z",
          }),
        })
      );
    });
    await flushQueue();

    timeline = client.getQueryData<JobListResponse>(timelineKey);
    expect(timeline?.jobs.map((j) => j.id)).toEqual(["root-1", "child-1"]);
  });

  it("coalesces queued progress events by job and keeps latest", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    const jobsKey = queryKeys.jobs();
    client.setQueryData(jobsKey, {
      jobs: [mkJob({ id: "job-p", function: "fn.p", function_name: "P", progress: 0 })],
      total: 1,
      has_more: false,
    } satisfies JobListResponse);

    renderWithQueryClient(client, (
      <EventStreamProvider>
        <div />
      </EventStreamProvider>
    ));

    const jobHandler = getJobMessageHandler();

    act(() => {
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.progress",
            job_id: "job-p",
            root_id: "job-p",
            progress: 0.1,
          }),
        })
      );
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.progress",
            job_id: "job-p",
            root_id: "job-p",
            progress: 0.9,
          }),
        })
      );
    });
    await flushQueue();

    const list = client.getQueryData<JobListResponse>(jobsKey);
    expect(list?.jobs[0].progress).toBe(0.9);
  });

  it("inserts terminal job events even when job.started was missed", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    const jobsKey = queryKeys.jobs({ limit: 50 });
    client.setQueryData(jobsKey, emptyList());

    renderWithQueryClient(client, (
      <EventStreamProvider>
        <div />
      </EventStreamProvider>
    ));

    const jobHandler = getJobMessageHandler();
    expect(jobHandler).toBeDefined();

    act(() => {
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.completed",
            job_id: "job-terminal",
            function: "fn.terminal",
            function_name: "Terminal",
            root_id: "job-terminal",
            attempt: 1,
            duration_ms: 42,
            completed_at: "2026-02-08T10:00:01Z",
          }),
        })
      );
    });
    await flushQueue();

    const list = client.getQueryData<JobListResponse>(jobsKey);
    expect(list?.jobs.map((j) => j.id)).toEqual(["job-terminal"]);
    expect(list?.jobs[0].status).toBe("complete");
    expect(list?.jobs[0].duration_ms).toBe(42);
    expect(list?.jobs[0].function).toBe("fn.terminal");
    expect(list?.jobs[0].function_name).toBe("Terminal");
  });

  it("keeps non-progress events under heavy progress backpressure", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    const key = queryKeys.jobs({ function: "fn.keep" });
    client.setQueryData(key, emptyList());

    renderWithQueryClient(client, (
      <EventStreamProvider>
        <div />
      </EventStreamProvider>
    ));

    const jobHandler = getJobMessageHandler();

    act(() => {
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.started",
            job_id: "job-keep",
            function: "fn.keep",
            function_name: "Keep",
            root_id: "job-keep",
            attempt: 1,
            max_retries: 0,
            started_at: "2026-02-08T10:00:00Z",
          }),
        })
      );

      for (let i = 0; i < 2200; i += 1) {
        jobHandler?.(
          new MessageEvent("message", {
            data: JSON.stringify({
              type: "job.progress",
              job_id: `spam-${i}`,
              root_id: `spam-${i}`,
              progress: i / 2200,
            }),
          })
        );
      }
    });

    await flushQueue();

    const list = client.getQueryData<JobListResponse>(key);
    expect(list?.jobs.map((j) => j.id)).toEqual(["job-keep"]);
  });

  it("applies API and worker snapshot stream updates to caches", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });

    client.setQueryData<ApisListResponse>(queryKeys.apis, {
      apis: [],
      total: 0,
    });
    client.setQueryData<ApiPageResponse>(queryKeys.api("orders"), {
      api: {
        name: "orders",
        docs_url: null,
        active: false,
        instance_count: 0,
        instances: [],
        endpoint_count: 0,
        requests_24h: 0,
        requests_per_min: 0,
        avg_latency_ms: 0,
        error_rate: 0,
        success_rate: 100,
        client_error_rate: 0,
        server_error_rate: 0,
      },
      endpoints: [],
      total_endpoints: 0,
    });
    client.setQueryData<ApiRequestEventsResponse>(
      queryKeys.apiRequestEvents({ limit: 3 }),
      {
        events: [],
        total: 0,
        has_more: false,
      }
    );
    client.setQueryData<WorkersListResponse>(queryKeys.workers, {
      workers: [],
      total: 0,
    });

    renderWithQueryClient(client, (
      <EventStreamProvider>
        <div />
      </EventStreamProvider>
    ));

    const apiHandler = getApiMessageHandler();
    const apiRequestEventsHandler = getApiRequestEventsMessageHandler();
    const workersHandler = getWorkersMessageHandler();
    expect(apiHandler).toBeDefined();
    expect(apiRequestEventsHandler).toBeDefined();
    expect(workersHandler).toBeDefined();

    act(() => {
      apiHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "api.snapshot",
            at: "2026-02-09T12:00:00Z",
            api: {
              api: {
                name: "orders",
                docs_url: "http://localhost:8001/docs",
                active: true,
                instance_count: 1,
                instances: [],
                endpoint_count: 2,
                requests_24h: 42,
                requests_per_min: 2.1,
                avg_latency_ms: 12,
                error_rate: 1.2,
                success_rate: 98.8,
                client_error_rate: 1.0,
                server_error_rate: 0.2,
              },
              endpoints: [],
              total_endpoints: 2,
            },
          }),
        })
      );
    });

    const detail = client.getQueryData<ApiPageResponse>(queryKeys.api("orders"));
    expect(detail?.api.requests_24h).toBe(42);

    const listFromApiSnapshot = client.getQueryData<ApisListResponse>(queryKeys.apis);
    expect(listFromApiSnapshot?.apis[0].name).toBe("orders");
    expect(listFromApiSnapshot?.apis[0].requests_24h).toBe(42);

    act(() => {
      apiHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "apis.snapshot",
            at: "2026-02-09T12:00:01Z",
            apis: {
              apis: [
                {
                  name: "billing",
                  active: true,
                  instance_count: 1,
                  instances: [],
                  endpoint_count: 1,
                  requests_24h: 10,
                  avg_latency_ms: 9,
                  error_rate: 0,
                  requests_per_min: 0.5,
                },
              ],
              total: 1,
            },
          }),
        })
      );
    });

    const list = client.getQueryData<ApisListResponse>(queryKeys.apis);
    expect(list?.apis.map((item) => item.name)).toEqual(["billing"]);
    expect(list?.total).toBe(1);

    act(() => {
      apiRequestEventsHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "api.request",
            at: "2026-02-09T12:00:03Z",
            request: {
              id: "evt_1",
              at: "2026-02-09T12:00:03Z",
              api_name: "orders",
              method: "POST",
              path: "/orders",
              status: 201,
              latency_ms: 14.2,
              instance_id: "api_a",
              sampled: false,
            },
          }),
        })
      );
    });

    const requestEvents = client.getQueryData<ApiRequestEventsResponse>(
      queryKeys.apiRequestEvents({ limit: 3 })
    );
    expect(requestEvents?.events[0]?.id).toBe("evt_1");
    expect(requestEvents?.events[0]?.api_name).toBe("orders");

    act(() => {
      workersHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "workers.snapshot",
            at: "2026-02-09T12:00:04Z",
            workers: {
              workers: [
                {
                  name: "worker-a",
                  active: true,
                  instance_count: 1,
                  instances: [],
                  functions: ["fn.task"],
                  function_names: { "fn.task": "Task" },
                  concurrency: 2,
                },
              ],
              total: 1,
            },
          }),
        })
      );
    });

    const workers = client.getQueryData<WorkersListResponse>(queryKeys.workers);
    expect(workers?.total).toBe(1);
    expect(workers?.workers[0]?.name).toBe("worker-a");
  });

  it("keeps window-mode caches isolated from live stream mutations", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });

    const liveJobsKey = queryKeys.jobs({ function: "fn.a", limit: 50 });
    const windowJobsKey = ["jobs", "window", { function: "fn.a" }] as const;
    const liveApiEventsKey = queryKeys.apiRequestEvents({ api_name: "orders", limit: 50 });
    const windowApiEventsKey = ["apis", "events-window", { api_name: "orders" }] as const;

    client.setQueryData<JobListResponse>(liveJobsKey, {
      jobs: [mkJob({ id: "job-live", function: "fn.a", function_name: "A", progress: 0 })],
      total: 1,
      has_more: false,
    });
    client.setQueryData<JobListResponse>(windowJobsKey, {
      jobs: [mkJob({ id: "job-window", function: "fn.a", function_name: "A", progress: 0 })],
      total: 1,
      has_more: false,
    });

    client.setQueryData<ApiRequestEventsResponse>(liveApiEventsKey, {
      events: [],
      total: 0,
      has_more: false,
    });
    client.setQueryData<ApiRequestEventsResponse>(windowApiEventsKey, {
      events: [],
      total: 0,
      has_more: false,
    });

    renderWithQueryClient(client, (
      <EventStreamProvider>
        <div />
      </EventStreamProvider>
    ));

    const jobHandler = getJobMessageHandler();
    const apiRequestEventsHandler = getApiRequestEventsMessageHandler();
    expect(jobHandler).toBeDefined();
    expect(apiRequestEventsHandler).toBeDefined();

    act(() => {
      jobHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.progress",
            job_id: "job-live",
            root_id: "job-live",
            progress: 0.75,
          }),
        })
      );
      apiRequestEventsHandler?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "api.request",
            at: "2026-02-09T12:00:02Z",
            request: {
              id: 99,
              api_name: "orders",
              method: "GET",
              path: "/orders",
              status: 200,
              latency_ms: 12.3,
              instance_id: "api-a",
              sampled: true,
              at: "2026-02-09T12:00:02Z",
            },
          }),
        })
      );
    });
    await flushQueue();

    const liveJobs = client.getQueryData<JobListResponse>(liveJobsKey);
    const windowJobs = client.getQueryData<JobListResponse>(windowJobsKey);
    expect(liveJobs?.jobs[0].progress).toBe(0.75);
    expect(windowJobs?.jobs[0].progress).toBe(0);

    const liveApiEvents = client.getQueryData<ApiRequestEventsResponse>(liveApiEventsKey);
    const windowApiEvents = client.getQueryData<ApiRequestEventsResponse>(windowApiEventsKey);
    expect(liveApiEvents?.events).toHaveLength(1);
    expect(windowApiEvents?.events).toHaveLength(0);
  });

  it("starts fallback invalidation only after sustained stream degradation", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { gcTime: Infinity } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    renderWithQueryClient(client, (
      <EventStreamProvider
        streams={{ jobs: true, apis: false, apiEvents: false, workers: false }}
      >
        <div />
      </EventStreamProvider>
    ));

    const jobStateHandler = getJobStateHandler();
    expect(jobStateHandler).toBeDefined();

    act(() => {
      jobStateHandler?.("connecting");
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(11_000);
    });
    expect(invalidateSpy).toHaveBeenCalledTimes(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(invalidateSpy).toHaveBeenCalled();
    const callsAfterFallback = invalidateSpy.mock.calls.length;

    act(() => {
      jobStateHandler?.("open");
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(invalidateSpy).toHaveBeenCalledTimes(callsAfterFallback);
  });
});
