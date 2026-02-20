import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Job } from "@/lib/types";
import { JobsTable } from "./jobs-table";

function mkJob(id: string): Job {
  return {
    id,
    job_key: id,
    function: "fn.key",
    function_name: "my_task",
    job_type: "task",
    source: { type: "task" },
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
    root_id: id,
    progress: 0.2,
    kwargs: {},
    checkpoint: null,
    checkpoint_at: null,
    result: null,
    error: null,
    duration_ms: null,
  };
}

describe("JobsTable", () => {
  it("calls onJobClick with selected job when row is clicked", async () => {
    const onJobClick = vi.fn();
    const user = userEvent.setup();

    render(<JobsTable jobs={[mkJob("job-123")]} onJobClick={onJobClick} />);

    await user.click(screen.getByText("job-123"));

    expect(onJobClick).toHaveBeenCalledTimes(1);
    expect(onJobClick.mock.calls[0][0]).toMatchObject({ id: "job-123" });
  });
});
