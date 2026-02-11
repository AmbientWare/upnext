import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ComponentType, ReactNode } from "react";

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    Link: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
  };
});

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
  (Route as unknown as { useParams: () => { name: string } }).useParams = () => ({
    name: "worker-a",
  });
  const Component = (Route as unknown as { options: { component: ComponentType } }).options.component;
  return render(
    <QueryClientProvider client={queryClient}>
      <Component />
    </QueryClientProvider>
  );
}

describe("WorkerDetailPage", () => {
  it("renders worker metrics and linked functions", async () => {
    getWorkersMock.mockResolvedValue({
      workers: [
        {
          name: "worker-a",
          active: true,
          instance_count: 2,
          instances: [
            {
              id: "worker-a-1",
              worker_name: "worker-a",
              started_at: "2026-02-08T10:00:00Z",
              last_heartbeat: "2026-02-08T10:01:00Z",
              functions: ["fn.alpha", "fn.beta"],
              function_names: { "fn.alpha": "alpha", "fn.beta": "beta" },
              concurrency: 2,
              active_jobs: 1,
              jobs_processed: 20,
              jobs_failed: 1,
              hostname: "host-1",
            },
            {
              id: "worker-a-2",
              worker_name: "worker-a",
              started_at: "2026-02-08T10:00:00Z",
              last_heartbeat: "2026-02-08T10:01:10Z",
              functions: ["fn.alpha"],
              function_names: { "fn.alpha": "alpha" },
              concurrency: 3,
              active_jobs: 2,
              jobs_processed: 15,
              jobs_failed: 0,
              hostname: "host-2",
            },
          ],
          functions: ["fn.alpha", "fn.beta"],
          function_names: { "fn.alpha": "alpha", "fn.beta": "beta" },
          concurrency: 2,
        },
      ],
      total: 1,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "worker-a" })).toBeInTheDocument();
    });

    expect(screen.getByText("3/5")).toBeInTheDocument();
    expect(screen.getByText("Processed Jobs")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
  });
});
