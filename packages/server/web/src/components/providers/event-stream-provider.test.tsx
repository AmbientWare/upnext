import { type ReactNode } from "react";
import { render, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { queryKeys } from "@/lib/conduit-api";
import type { Job, JobListResponse } from "@/lib/types";
import { EventStreamProvider } from "./event-stream-provider";

let capturedOnMessage: ((event: MessageEvent) => void) | undefined;

vi.mock("@/hooks/use-event-source", () => ({
  useEventSource: (_url: string, options: { onMessage?: (event: MessageEvent) => void }) => {
    capturedOnMessage = options.onMessage;
    return { current: null };
  },
}));

function mkJob(partial: Partial<Job> & Pick<Job, "id">): Job {
  return {
    id: partial.id,
    function: partial.function ?? "fn",
    function_name: partial.function_name ?? "fn",
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
    metadata: partial.metadata ?? {},
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

async function flushQueue() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(120);
    await Promise.resolve();
  });
}

describe("EventStreamProvider", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    capturedOnMessage = undefined;
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

    expect(capturedOnMessage).toBeDefined();

    act(() => {
      capturedOnMessage?.(
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

    act(() => {
      capturedOnMessage?.(
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
      capturedOnMessage?.(
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

    act(() => {
      capturedOnMessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "job.progress",
            job_id: "job-p",
            root_id: "job-p",
            progress: 0.1,
          }),
        })
      );
      capturedOnMessage?.(
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

    act(() => {
      capturedOnMessage?.(
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
        capturedOnMessage?.(
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
});
