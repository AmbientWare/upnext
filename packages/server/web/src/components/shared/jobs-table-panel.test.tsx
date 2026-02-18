import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Job } from "@/lib/types";
import { JobsTablePanel } from "./jobs-table-panel";

function mkJob(id: string, status: Job["status"], functionName: string): Job {
  return {
    id,
    function: functionName,
    function_name: functionName,
    job_type: "task",
    source: { type: "task" },
    status,
    created_at: "2026-02-08T10:00:00Z",
    scheduled_at: "2026-02-08T10:00:00Z",
    started_at: "2026-02-08T10:00:00Z",
    completed_at: status === "complete" ? "2026-02-08T10:00:05Z" : null,
    attempts: 1,
    max_retries: 0,
    timeout: null,
    worker_id: "worker-1",
    parent_id: null,
    root_id: id,
    progress: status === "active" ? 0.2 : 1,
    kwargs: {},
    checkpoint: null,
    checkpoint_at: null,
    dlq_replayed_from: null,
    dlq_failed_at: null,
    result: null,
    error: null,
    duration_ms: status === "complete" ? 5000 : null,
  };
}

describe("JobsTablePanel", () => {
  it("filters jobs by selected status", async () => {
    const user = userEvent.setup();

    render(
      <JobsTablePanel
        showFilters
        jobs={[
          mkJob("job-active-123", "active", "active_fn"),
          mkJob("job-failed-456", "failed", "failed_fn"),
        ]}
      />
    );

    expect(screen.getByText("active_fn")).toBeInTheDocument();
    expect(screen.getByText("failed_fn")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Failed" }));

    expect(screen.queryByText("active_fn")).not.toBeInTheDocument();
    expect(screen.getByText("failed_fn")).toBeInTheDocument();
  });
});
