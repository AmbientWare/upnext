import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ApiRequestEvent } from "@/lib/types";
import { ApiRequestsTable } from "./api-requests-table";

function mkEvent(overrides: Partial<ApiRequestEvent> = {}): ApiRequestEvent {
  return {
    id: "evt_1",
    at: "2026-02-09T12:00:00Z",
    api_name: "orders",
    method: "GET",
    path: "/orders",
    status: 200,
    latency_ms: 11.2,
    instance_id: "api_a",
    sampled: false,
    ...overrides,
  };
}

describe("ApiRequestsTable", () => {
  it("calls onApiClick when clicking a row with api_name", async () => {
    const onApiClick = vi.fn();
    const user = userEvent.setup();

    render(
      <ApiRequestsTable
        events={[mkEvent()]}
        onApiClick={onApiClick}
      />
    );

    await user.click(screen.getByText("orders"));

    expect(onApiClick).toHaveBeenCalledWith("orders");
  });
});
