import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ComponentType, ReactNode } from "react";

vi.mock("@tanstack/react-router", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router");
  return {
    ...actual,
    Link: ({ children, ...props }: { children: ReactNode }) => <a {...props}>{children}</a>,
    useNavigate: () => vi.fn(),
  };
});

const getApiMock = vi.fn();
const getApiRequestEventsMock = vi.fn();

vi.mock("@/lib/upnext-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/upnext-api")>("@/lib/upnext-api");
  return {
    ...actual,
    getApi: (...args: unknown[]) => getApiMock(...args),
    getApiRequestEvents: (...args: unknown[]) => getApiRequestEventsMock(...args),
  };
});

vi.mock("@/hooks/use-event-source", () => ({
  useEventSource: () => ({ current: null }),
}));

import { Route } from "./index";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  (Route as unknown as { useParams: () => { name: string } }).useParams = () => ({
    name: "orders",
  });
  const Component = (Route as unknown as { options: { component: ComponentType } }).options.component;
  return render(
    <QueryClientProvider client={queryClient}>
      <Component />
    </QueryClientProvider>
  );
}

describe("ApiDetailPage", () => {
  it("renders overview, docs link, and route metrics tree", async () => {
    getApiRequestEventsMock.mockResolvedValue({
      events: [],
      total: 0,
    });
    getApiMock.mockResolvedValue({
      api: {
        name: "orders",
        docs_url: "http://localhost:8001/docs",
        active: true,
        instance_count: 1,
        instances: [],
        endpoint_count: 2,
        requests_24h: 180,
        requests_per_min: 2.5,
        avg_latency_ms: 24.8,
        error_rate: 4.5,
        success_rate: 95.5,
        client_error_rate: 3.0,
        server_error_rate: 1.5,
      },
      endpoints: [
        {
          method: "GET",
          path: "/orders",
          requests_24h: 120,
          requests_per_min: 1.5,
          avg_latency_ms: 18.2,
          p50_latency_ms: 0,
          p95_latency_ms: 0,
          p99_latency_ms: 0,
          error_rate: 2.0,
          success_rate: 98.0,
          client_error_rate: 1.0,
          server_error_rate: 1.0,
          status_2xx: 118,
          status_4xx: 1,
          status_5xx: 1,
          last_request_at: null,
        },
        {
          method: "POST",
          path: "/orders/create",
          requests_24h: 60,
          requests_per_min: 1.0,
          avg_latency_ms: 38.1,
          p50_latency_ms: 0,
          p95_latency_ms: 0,
          p99_latency_ms: 0,
          error_rate: 10.0,
          success_rate: 90.0,
          client_error_rate: 5.0,
          server_error_rate: 5.0,
          status_2xx: 54,
          status_4xx: 3,
          status_5xx: 3,
          last_request_at: null,
        },
      ],
      total_endpoints: 2,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "orders" })).toBeInTheDocument();
    });

    expect(screen.getByText("Docs")).toHaveAttribute("href", "http://localhost:8001/docs");
    expect(screen.getAllByText("/orders").length).toBeGreaterThan(0);
    expect(screen.getAllByText("/orders/create").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2 routes").length).toBeGreaterThan(0);
  });
});
