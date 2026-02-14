import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./error-boundary";

function ThrowingChild({ error }: { error: Error }): never {
  throw error;
}

describe("ErrorBoundary", () => {
  it("renders children when no error occurs", () => {
    render(
      <ErrorBoundary>
        <p>content</p>
      </ErrorBoundary>
    );
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("renders default fallback with error message on throw", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <ThrowingChild error={new Error("test boom")} />
      </ErrorBoundary>
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("test boom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("renders custom fallback when provided", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={<div>custom error ui</div>}>
        <ThrowingChild error={new Error("ignored")} />
      </ErrorBoundary>
    );
    expect(screen.getByText("custom error ui")).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it("recovers when Try again is clicked", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    let shouldThrow = true;

    function MaybeThrow() {
      if (shouldThrow) throw new Error("recoverable");
      return <p>recovered</p>;
    }

    render(
      <ErrorBoundary>
        <MaybeThrow />
      </ErrorBoundary>
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();

    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("recovered")).toBeInTheDocument();
  });
});
