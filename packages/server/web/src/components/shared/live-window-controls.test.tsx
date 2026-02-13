import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LiveWindowControls } from "./live-window-controls";

describe("LiveWindowControls", () => {
  it("enables live mode from the popover action", async () => {
    const user = userEvent.setup();
    const onLiveChange = vi.fn();
    const onPresetChange = vi.fn();
    const onDateRangeChange = vi.fn();

    render(
      <LiveWindowControls
        live={false}
        onLiveChange={onLiveChange}
        preset="custom"
        onPresetChange={onPresetChange}
        dateRange={{
          from: new Date("2026-02-13T10:00:00.000Z"),
          to: new Date("2026-02-13T11:00:00.000Z"),
        }}
        onDateRangeChange={onDateRangeChange}
      />
    );

    await user.click(screen.getByRole("button", { name: /open live window controls/i }));
    await user.click(screen.getByRole("button", { name: /go live/i }));

    expect(onLiveChange).toHaveBeenCalledWith(true);
    expect(onPresetChange).not.toHaveBeenCalled();
    expect(onDateRangeChange).not.toHaveBeenCalled();
  });

  it("applies a preset range and exits live mode", async () => {
    const user = userEvent.setup();
    const onLiveChange = vi.fn();
    const onPresetChange = vi.fn();
    const onDateRangeChange = vi.fn();

    render(
      <LiveWindowControls
        live={true}
        onLiveChange={onLiveChange}
        preset="custom"
        onPresetChange={onPresetChange}
        dateRange={undefined}
        onDateRangeChange={onDateRangeChange}
      />
    );

    await user.click(screen.getByRole("button", { name: /open live window controls/i }));
    await user.click(screen.getByRole("button", { name: "Last 1h" }));

    expect(onPresetChange).toHaveBeenCalledWith("1h");
    expect(onLiveChange).toHaveBeenCalledWith(false);
    expect(onDateRangeChange).toHaveBeenCalledTimes(1);
    const applied = onDateRangeChange.mock.calls[0][0] as { from: Date; to: Date };
    expect(applied.to.getTime() - applied.from.getTime()).toBe(60 * 60 * 1000);
  });

  it("applies a custom range and clamps end before start", async () => {
    const user = userEvent.setup();
    const onLiveChange = vi.fn();
    const onPresetChange = vi.fn();
    const onDateRangeChange = vi.fn();

    render(
      <LiveWindowControls
        live={false}
        onLiveChange={onLiveChange}
        preset="custom"
        onPresetChange={onPresetChange}
        dateRange={{
          from: new Date("2026-02-13T10:00:00.000Z"),
          to: new Date("2026-02-13T10:30:00.000Z"),
        }}
        onDateRangeChange={onDateRangeChange}
      />
    );

    await user.click(screen.getByRole("button", { name: /open live window controls/i }));

    const fromInput = screen.getByLabelText("From time");
    fireEvent.change(fromInput, { target: { value: "11:45" } });

    await user.click(screen.getByRole("button", { name: /apply range/i }));

    expect(onPresetChange).toHaveBeenCalledWith("custom");
    expect(onLiveChange).toHaveBeenCalledWith(false);
    expect(onDateRangeChange).toHaveBeenCalledTimes(1);

    const applied = onDateRangeChange.mock.calls[0][0] as { from: Date; to: Date };
    expect(applied.from.getHours()).toBe(11);
    expect(applied.from.getMinutes()).toBe(45);
    expect(applied.to.getHours()).toBe(11);
    expect(applied.to.getMinutes()).toBe(45);
    expect(applied.to.getSeconds()).toBe(59);
  });
});
