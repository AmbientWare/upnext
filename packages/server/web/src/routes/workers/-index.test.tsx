import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComponentType } from "react";

const getWorkersMock = vi.fn();

vi.mock("@/lib/upnext-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/upnext-api")>("@/lib/upnext-api");
  return {
    ...actual,
    getWorkers: (...args: unknown[]) => getWorkersMock(...args),
  };
});

import { Route } from "./index";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  const Component = (Route as unknown as { options: { component: ComponentType } }).options.component;
  return render(
    <QueryClientProvider client={queryClient}>
      <Component />
    </QueryClientProvider>
  );
}

describe("WorkersPage filters", () => {
  it("applies search and default active filtering", async () => {
    getWorkersMock.mockResolvedValue({
      workers: [
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
              active_jobs: 0,
              jobs_processed: 0,
              jobs_failed: 0,
            },
          ],
          functions: ["fn.alpha"],
          function_names: { "fn.alpha": "alpha" },
          concurrency: 2,
        },
        {
          name: "worker-b",
          active: false,
          instance_count: 0,
          instances: [],
          functions: ["fn.beta"],
          function_names: { "fn.beta": "beta" },
          concurrency: 1,
        },
      ],
      total: 2,
    });

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("worker-a")).toBeInTheDocument();
    });

    expect(screen.queryByText("worker-b")).not.toBeInTheDocument();

    const search = screen.getByPlaceholderText("Search workers...");
    await user.type(search, "worker-a");
    expect(screen.getByText("worker-a")).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "fn.alpha");
    expect(screen.getByText("worker-a")).toBeInTheDocument();
  });
});
