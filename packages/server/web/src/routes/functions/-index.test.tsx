import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComponentType } from "react";

const getFunctionsMock = vi.fn();

vi.mock("@/lib/upnext-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/upnext-api")>("@/lib/upnext-api");
  return {
    ...actual,
    getFunctions: (...args: unknown[]) => getFunctionsMock(...args),
  };
});

vi.mock("./-components/functions-table", () => ({
  FunctionsTable: ({ functions }: { functions: Array<{ key: string; name: string }> }) => (
    <div data-testid="functions-table">
      {functions.map((fn) => (
        <div key={fn.key}>{fn.name}</div>
      ))}
    </div>
  ),
}));

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

describe("FunctionsPage filters", () => {
  it("applies search with default active status filtering", async () => {
    getFunctionsMock.mockResolvedValue({
      functions: [
        {
          key: "task_a",
          name: "alpha_task",
          type: "task",
          active: true,
          workers: ["w1"],
          runs_24h: 3,
          success_rate: 100,
          avg_duration_ms: 10,
          timeout: 30,
          max_retries: 0,
        },
        {
          key: "task_b",
          name: "beta_task",
          type: "task",
          active: false,
          workers: ["w2"],
          runs_24h: 2,
          success_rate: 50,
          avg_duration_ms: 20,
          timeout: 30,
          max_retries: 1,
        },
      ],
      total: 2,
    });

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alpha_task")).toBeInTheDocument();
    });

    // Default status filter is active, so inactive row is hidden.
    expect(screen.queryByText("beta_task")).not.toBeInTheDocument();

    const search = screen.getByPlaceholderText("Search functions...");
    await user.type(search, "alpha");
    expect(screen.getByText("alpha_task")).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "beta");
    expect(screen.queryByText("alpha_task")).not.toBeInTheDocument();
  });
});
