import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Job } from "@/lib/types";
import { JobDetailsPanel } from "./job-details-panel";

function mkJob(): Job {
  return {
    id: "job-details-1",
    function: "fn.long",
    function_name: "fn.long",
    status: "complete",
    created_at: "2026-02-08T10:00:00Z",
    scheduled_at: "2026-02-08T10:00:00Z",
    started_at: "2026-02-08T10:00:01Z",
    completed_at: "2026-02-08T10:00:10Z",
    attempts: 1,
    max_retries: 0,
    timeout: null,
    worker_id: "worker-xyz",
    parent_id: null,
    root_id: "job-details-1",
    progress: 1,
    kwargs: {
      arg: "x".repeat(120),
    },
    metadata: {
      stream_key:
        "upnext:fn:very_long_function_name:stream:with:extra:segments:that:force:horizontal:overflow",
    },
    result: null,
    error: null,
    duration_ms: 9000,
  };
}

describe("JobDetailsPanel", () => {
  it("renders bounded panel sections and provides horizontal JSON scroll containers", () => {
    const { container } = render(<JobDetailsPanel job={mkJob()} />);

    expect(screen.getByText("Job Details")).toBeInTheDocument();
    expect(screen.getByText("Metadata")).toBeInTheDocument();
    expect(screen.getByText("Arguments")).toBeInTheDocument();

    const horizontalScrollContainers = container.querySelectorAll(".overflow-x-auto");
    expect(horizontalScrollContainers.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Worker")).toBeInTheDocument();
    expect(screen.getByText("Attempts")).toBeInTheDocument();
  });
});
