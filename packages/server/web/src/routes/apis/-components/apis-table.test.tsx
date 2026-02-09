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

import { ApisTable } from "./apis-table";

describe("ApisTable", () => {
  it("navigates when the row is clicked", async () => {
    const user = userEvent.setup();

    render(
      <ApisTable
        apis={[
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
                hostname: "localhost",
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
        ]}
      />
    );

    const row = screen.getByRole("link", { name: /orders-api/i });
    await user.click(row);

    expect(navigateMock).toHaveBeenCalledWith({ to: "/apis/$name", params: { name: "orders-api" } });
  });
});
