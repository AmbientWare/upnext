import { Clock3 } from "lucide-react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  formatTimeWindowLabel,
  type TimeWindowPreset,
} from "./live-window-utils";

const PRESET_OPTIONS: Array<{ value: Exclude<TimeWindowPreset, "custom">; label: string }> = [
  { value: "15m", label: "Last 15m" },
  { value: "1h", label: "Last 1h" },
  { value: "6h", label: "Last 6h" },
  { value: "24h", label: "Last 24h" },
];

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
      <Popover>
        <PopoverTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            className="h-8 max-w-[190px] justify-start px-3 text-xs font-normal"
          >
            <Clock3 className="h-3 w-3 shrink-0" />
            <span className="truncate">{live ? "Live" : formatTimeWindowLabel(preset, dateRange)}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[300px] p-3">
          <div className="space-y-3">
            <Button
              type="button"
              size="xs"
              variant={live ? "default" : "outline"}
              className="w-full justify-start"
              onClick={() => onLiveChange(true)}
            >
              Live (auto-refresh)
            </Button>

            <div className="grid grid-cols-2 gap-1">
              {PRESET_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  size="xs"
                  variant={!live && preset === option.value ? "default" : "outline"}
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
