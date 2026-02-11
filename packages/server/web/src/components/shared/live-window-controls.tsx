import { Clock3 } from "lucide-react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type TimeWindowPreset = "15m" | "1h" | "6h" | "24h" | "custom";

interface TimeWindowBounds {
  from: Date;
  to: Date;
}

const PRESET_OPTIONS: Array<{ value: Exclude<TimeWindowPreset, "custom">; label: string }> = [
  { value: "15m", label: "Last 15m" },
  { value: "1h", label: "Last 1h" },
  { value: "6h", label: "Last 6h" },
  { value: "24h", label: "Last 24h" },
];

function formatDateShort(date: Date): string {
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
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
  from.setHours(0, 0, 0, 0);

  const to = dateRange.to ? new Date(dateRange.to) : new Date(dateRange.from);
  to.setHours(23, 59, 59, 999);

  return { from, to };
}

export function formatTimeWindowLabel(
  preset: TimeWindowPreset,
  dateRange: DateRange | undefined
): string {
  if (preset === "15m") return "Window: 15m";
  if (preset === "1h") return "Window: 1h";
  if (preset === "6h") return "Window: 6h";
  if (preset === "24h") return "Window: 24h";
  if (!dateRange?.from) return "Window: Custom";

  if (!dateRange.to) {
    return `Window: ${formatDateShort(dateRange.from)}`;
  }

  return `Window: ${formatDateShort(dateRange.from)} - ${formatDateShort(dateRange.to)}`;
}

interface LiveWindowControlsProps {
  live: boolean;
  onLiveChange: (live: boolean) => void;
  preset: TimeWindowPreset;
  onPresetChange: (preset: TimeWindowPreset) => void;
  dateRange: DateRange | undefined;
  onDateRangeChange: (range: DateRange | undefined) => void;
  className?: string;
}

export function LiveWindowControls({
  live,
  onLiveChange,
  preset,
  onPresetChange,
  dateRange,
  onDateRangeChange,
  className,
}: LiveWindowControlsProps) {
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <Button
        size="xs"
        variant={live ? "default" : "outline"}
        onClick={() => onLiveChange(!live)}
      >
        Live
      </Button>

      <Popover>
        <PopoverTrigger asChild>
          <Button size="xs" variant="outline" className="max-w-[190px] justify-start">
            <Clock3 className="h-3 w-3 shrink-0" />
            <span className="truncate">{formatTimeWindowLabel(preset, dateRange)}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[300px] p-3">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-1">
              {PRESET_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  size="xs"
                  variant={preset === option.value ? "default" : "outline"}
                  onClick={() => {
                    onPresetChange(option.value);
                    onLiveChange(false);
                  }}
                >
                  {option.label}
                </Button>
              ))}
            </div>

            <div className="rounded-md border border-input">
              <Calendar
                mode="range"
                selected={dateRange}
                onSelect={(range) => {
                  onDateRangeChange(range);
                  onPresetChange("custom");
                  onLiveChange(false);
                }}
                numberOfMonths={1}
                className="mx-auto"
              />
            </div>

            <p className="text-[10px] text-muted-foreground">
              Selecting a window pauses live updates.
            </p>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
