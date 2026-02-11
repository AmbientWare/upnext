import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const navigateMock = vi.fn();

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

import { WorkersTable } from "./workers-table";

describe("WorkersTable", () => {
  it("navigates when a worker row is clicked", async () => {
    const user = userEvent.setup();

    render(
      <WorkersTable
        workers={[
          {
            name: "worker-a",
            active: true,
            instance_count: 1,
            instances: [
              {
                id: "worker_a_1",
                worker_name: "worker-a",
                started_at: "2026-02-08T10:00:00Z",
                last_heartbeat: "2026-02-08T10:00:10Z",
                functions: ["fn.alpha"],
                function_names: { "fn.alpha": "alpha" },
                concurrency: 2,
                active_jobs: 1,
                jobs_processed: 10,
                jobs_failed: 1,
                hostname: "host-1",
              },
            ],
            functions: ["fn.alpha"],
            function_names: { "fn.alpha": "alpha" },
            concurrency: 2,
          },
        ]}
      />
    );

    await user.click(screen.getByRole("link", { name: /worker-a/i }));
    expect(navigateMock).toHaveBeenCalledWith({ to: "/workers/$name", params: { name: "worker-a" } });
  });
});
