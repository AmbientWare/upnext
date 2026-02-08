import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComponentType } from "react";

const getApisMock = vi.fn();

vi.mock("@/lib/conduit-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/conduit-api")>("@/lib/conduit-api");
  return {
    ...actual,
    getApis: (...args: unknown[]) => getApisMock(...args),
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

describe("ApisPage filters", () => {
  it("applies search with default active status filtering", async () => {
    getApisMock.mockResolvedValue({
      apis: [
        {
          name: "orders-api",
          active: true,
          instance_count: 1,
          instances: [
            {
              id: "api-1",
              api_name: "orders-api",
              started_at: "2026-02-08T10:00:00Z",
              last_heartbeat: "2026-02-08T10:00:10Z",
              host: "0.0.0.0",
              port: 8080,
              endpoints: ["GET:/orders"],
            },
          ],
          endpoint_count: 1,
          requests_24h: 200,
          avg_latency_ms: 20,
          error_rate: 0.1,
          requests_per_min: 4,
        },
        {
          name: "billing-api",
          active: false,
          instance_count: 0,
          instances: [],
          endpoint_count: 1,
          requests_24h: 50,
          avg_latency_ms: 30,
          error_rate: 0,
          requests_per_min: 1,
        },
      ],
      total: 2,
    });

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("orders-api")).toBeInTheDocument();
    });

    expect(screen.queryByText("billing-api")).not.toBeInTheDocument();

    const search = screen.getByPlaceholderText("Search APIs...");
    await user.type(search, "orders");
    expect(screen.getByText("orders-api")).toBeInTheDocument();
  });
});
