import type { DateRange } from "react-day-picker";

export type TimeWindowPreset = "15m" | "1h" | "6h" | "24h" | "custom";
export const LIVE_LIST_LIMIT = 50;
export const LIVE_REFRESH_INTERVAL_MS = 5_000;

interface TimeWindowBounds {
  from: Date;
  to: Date;
}

export function getTimeWindowBounds(
  preset: TimeWindowPreset,
  dateRange: DateRange | undefined
): TimeWindowBounds | null {
  const now = new Date();
  const nowTime = now.getTime();

  if (preset === "15m") {
    return { from: new Date(nowTime - 15 * 60 * 1000), to: now };
  }
  if (preset === "1h") {
    return { from: new Date(nowTime - 60 * 60 * 1000), to: now };
  }
  if (preset === "6h") {
    return { from: new Date(nowTime - 6 * 60 * 60 * 1000), to: now };
  }
  if (preset === "24h") {
    return { from: new Date(nowTime - 24 * 60 * 60 * 1000), to: now };
  }

  if (!dateRange?.from) {
    return null;
  }

  const from = new Date(dateRange.from);
  const to = new Date(dateRange.to ? dateRange.to : dateRange.from);
  if (to.getTime() < from.getTime()) {
    return { from: to, to: from };
  }
  return { from, to };
}

function formatDateTimeShort(date: Date): string {
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatTimeWindowLabel(
  preset: TimeWindowPreset,
  dateRange: DateRange | undefined
): string {
  if (preset === "15m") return "15m";
  if (preset === "1h") return "1h";
  if (preset === "6h") return "6h";
  if (preset === "24h") return "24h";
  if (!dateRange?.from) return "Custom";

  const fromLabel = formatDateTimeShort(dateRange.from);
  const toLabel = formatDateTimeShort(dateRange.to ? dateRange.to : dateRange.from);
  return `${fromLabel} - ${toLabel}`;
}
