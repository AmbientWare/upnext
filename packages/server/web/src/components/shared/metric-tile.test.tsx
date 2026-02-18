import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricTile } from "./metric-tile";

describe("MetricTile", () => {
  it("renders label, value, and optional subtext", () => {
    render(
      <MetricTile
        label="Runs"
        value="128"
        sub="Last 24 hours"
        tone="text-emerald-400"
        className="custom-card"
        valueClassName="custom-value"
      />
    );

    expect(screen.getByText("Runs")).toBeInTheDocument();
    expect(screen.getByText("128")).toBeInTheDocument();
    expect(screen.getByText("Last 24 hours")).toBeInTheDocument();
    expect(screen.getByText("128")).toHaveClass("custom-value");
    expect(screen.getByText("128").parentElement).toHaveClass("custom-card");
  });
});
