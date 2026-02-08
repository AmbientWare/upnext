import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAnimatedNumber } from "./use-animated-number";

function NumberHarness({ value }: { value: string | number }) {
  const display = useAnimatedNumber(value, 120);
  return <div data-testid="value">{display}</div>;
}

describe("useAnimatedNumber", () => {
  it("animates numeric values over time", async () => {
    vi.useFakeTimers();

    const { rerender } = render(<NumberHarness value={10} />);
    expect(screen.getByTestId("value").textContent).toBe("10");

    rerender(<NumberHarness value={20} />);
    await vi.advanceTimersByTimeAsync(160);

    expect(screen.getByTestId("value").textContent).toBe("20");
    vi.useRealTimers();
  });

  it("returns non-numeric input unchanged", () => {
    render(<NumberHarness value={"n/a"} />);
    expect(screen.getByTestId("value").textContent).toBe("n/a");
  });
});
