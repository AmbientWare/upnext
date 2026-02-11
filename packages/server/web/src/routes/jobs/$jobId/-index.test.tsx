import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComponentType } from "react";

const getJobTimelineMock = vi.fn();
let capturedArtifactsProps: { selectedJobId: string; jobs: Array<{ id: string }> } | null = null;

vi.mock("@/lib/upnext-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/upnext-api")>("@/lib/upnext-api");
  return {
    ...actual,
    getJobTimeline: (...args: unknown[]) => getJobTimelineMock(...args),
  };
});

vi.mock("./-components/job-run-header", () => ({
  JobRunHeader: () => <div data-testid="run-header" />,
}));
vi.mock("./-components/job-timeline-panel", () => ({
  JobTimelinePanel: () => <div data-testid="timeline" />,
}));
vi.mock("./-components/job-task-runs-tab", () => ({
  JobTaskRunsTab: () => <div data-testid="task-runs" />,
}));
vi.mock("./-components/job-logs-tab", () => ({
  JobLogsTab: () => <div data-testid="logs" />,
}));
vi.mock("./-components/job-artifacts-tab", () => ({
  JobArtifactsTab: (props: { selectedJobId: string; jobs: Array<{ id: string }> }) => {
    capturedArtifactsProps = props;
    return <div data-testid="artifacts-tab" />;
  },
}));
vi.mock("./-components/job-details-panel", () => ({
  JobDetailsPanel: () => <div data-testid="details" />,
}));
vi.mock("./-components/skeletons", () => ({
  JobDetailSkeleton: () => <div data-testid="skeleton" />,
}));

import { Route } from "./index";
import { queryKeys } from "@/lib/upnext-api";

describe("Job detail page artifacts refresh", () => {
  it("shows refresh button in artifacts tab and refetches selected job artifacts", async () => {
    getJobTimelineMock.mockResolvedValue({
      jobs: [
        {
          id: "job-root",
          function: "fn.root",
          function_name: "root",
          status: "active",
          created_at: "2026-02-08T10:00:00Z",
          scheduled_at: "2026-02-08T10:00:00Z",
          started_at: "2026-02-08T10:00:00Z",
          completed_at: null,
          attempts: 1,
          max_retries: 0,
          timeout: null,
          worker_id: "worker-1",
          parent_id: null,
          root_id: "job-root",
          progress: 0.2,
          kwargs: {},
          metadata: {},
          result: null,
          error: null,
          duration_ms: null,
        },
      ],
      total: 1,
      has_more: false,
    });

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    const refetchSpy = vi.spyOn(queryClient, "refetchQueries");

    const useParamsSpy = vi.spyOn(Route as unknown as { useParams: () => { jobId: string } }, "useParams");
    useParamsSpy.mockReturnValue({ jobId: "job-root" });

  const Component = (Route as unknown as { options: { component: ComponentType } }).options.component;
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <Component />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("run-header")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: "Artifacts" }));

    const refresh = await screen.findByRole("button", { name: "Refresh artifacts" });
    await user.click(refresh);

    expect(refetchSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.jobArtifacts("job-root"),
      exact: true,
    });
    expect(capturedArtifactsProps?.selectedJobId).toBe("job-root");
    expect(capturedArtifactsProps?.jobs.map((job) => job.id)).toContain("job-root");
  });
});
