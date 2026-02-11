import type { DateRange } from "react-day-picker";

export type TimeWindowPreset = "15m" | "1h" | "6h" | "24h" | "custom";

interface TimeWindowBounds {
  from: Date;
  to: Date;
}

function normalizeToDayStart(date: Date): Date {
  const normalized = new Date(date);
  normalized.setHours(0, 0, 0, 0);
  return normalized;
}

function normalizeToDayEnd(date: Date): Date {
  const normalized = new Date(date);
  normalized.setHours(23, 59, 59, 999);
  return normalized;
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

  const from = normalizeToDayStart(dateRange.from);
  const to = normalizeToDayEnd(dateRange.to ? dateRange.to : dateRange.from);

  return { from, to };
}

function formatDateShort(date: Date): string {
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
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

  if (!dateRange.to) {
    return formatDateShort(dateRange.from);
  }

  return `${formatDateShort(dateRange.from)} - ${formatDateShort(dateRange.to)}`;
}
