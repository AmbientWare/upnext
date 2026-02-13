import { ChevronDownIcon, Clock3, Radio } from "lucide-react";
import { memo, useState } from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  formatTimeWindowLabel,
  getTimeWindowBounds,
  type TimeWindowPreset,
} from "./live-window-utils";

const PRESET_OPTIONS: Array<{ value: Exclude<TimeWindowPreset, "custom">; label: string }> = [
  { value: "15m", label: "Last 15m" },
  { value: "1h", label: "Last 1h" },
  { value: "6h", label: "Last 6h" },
  { value: "24h", label: "Last 24h" },
];

interface DraftRange {
  from: Date;
  to: Date;
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

function toTimeStr(d: Date): string {
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function parseTime(value: string): { hours: number; minutes: number } | null {
  const m = /^(\d{1,2}):(\d{2})/.exec(value);
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return { hours: h, minutes: min };
}

function formatDateBtn(d: Date): string {
  return d.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function makeDraft(preset: TimeWindowPreset, dateRange: DateRange | undefined): DraftRange {
  const bounds = getTimeWindowBounds(preset, dateRange) ?? getTimeWindowBounds("1h", undefined);
  if (bounds) return { from: new Date(bounds.from), to: new Date(bounds.to) };
  const now = new Date();
  return { from: new Date(now.getTime() - 3_600_000), to: now };
}

type CalendarTarget = "from" | "to" | null;

export const LiveWindowControls = memo(function LiveWindowControls({
  live,
  onLiveChange,
  preset,
  onPresetChange,
  dateRange,
  onDateRangeChange,
  className,
}: LiveWindowControlsProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DraftRange>(() => makeDraft(preset, dateRange));
  const [calTarget, setCalTarget] = useState<CalendarTarget>(null);

  const applyPreset = (p: Exclude<TimeWindowPreset, "custom">) => {
    const bounds = getTimeWindowBounds(p, undefined);
    if (bounds) onDateRangeChange({ from: bounds.from, to: bounds.to });
    onPresetChange(p);
    onLiveChange(false);
    setOpen(false);
  };

  const applyCustom = () => {
    const { from, to } = draft.from > draft.to
      ? { from: new Date(draft.to), to: new Date(draft.from) }
      : { from: new Date(draft.from), to: new Date(draft.to) };
    onDateRangeChange({ from, to });
    onPresetChange("custom");
    onLiveChange(false);
    setOpen(false);
  };

  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) {
            setDraft(makeDraft(preset, dateRange));
            setCalTarget(null);
          }
        }}
      >
        <PopoverTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            className="h-8 max-w-[260px] justify-between gap-2 px-3 text-xs font-normal"
            aria-label="Open live window controls"
          >
            <span className="inline-flex min-w-0 items-center gap-1.5">
              {live ? (
                <Radio className="h-3 w-3 shrink-0 text-emerald-500" />
              ) : (
                <Clock3 className="h-3 w-3 shrink-0" />
              )}
              <span className="truncate">
                {live ? "Live" : formatTimeWindowLabel(preset, dateRange)}
              </span>
            </span>
            <ChevronDownIcon className="h-3 w-3 shrink-0 text-muted-foreground" />
          </Button>
        </PopoverTrigger>

        <PopoverContent align="end" className="w-[min(95vw,420px)] p-3">
          <div className="space-y-3">
            <Button
              type="button"
              size="xs"
              variant={live ? "default" : "outline"}
              className="h-7 w-full justify-center px-2 text-[11px]"
              onClick={() => {
                onLiveChange(true);
                setOpen(false);
              }}
            >
              <Radio className="h-3 w-3 shrink-0" />
              Go Live
            </Button>

            <div className="grid grid-cols-2 gap-1">
              {PRESET_OPTIONS.map((opt) => (
                <Button
                  key={opt.value}
                  type="button"
                  size="xs"
                  variant={!live && preset === opt.value ? "default" : "outline"}
                  className="h-7 px-2 text-[11px]"
                  onClick={() => applyPreset(opt.value)}
                >
                  {opt.label}
                </Button>
              ))}
            </div>

            <div className="rounded-md border border-input p-2">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-[11px] font-medium text-foreground">Custom range</p>
                <span className="text-[10px] mono text-muted-foreground">
                  {formatDateBtn(draft.from)} - {formatDateBtn(draft.to)}
                </span>
              </div>

              {/* From row */}
              <div className="flex gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <label className="px-1 text-[10px] text-muted-foreground">From date</label>
                  <Button
                    variant="outline"
                    className="h-8 w-full justify-between px-2 text-[11px] font-normal"
                    onClick={() => setCalTarget(calTarget === "from" ? null : "from")}
                  >
                    {formatDateBtn(draft.from)}
                    <ChevronDownIcon className="h-3 w-3 shrink-0 text-muted-foreground" />
                  </Button>
                </div>
                <div className="flex w-[122px] shrink-0 flex-col gap-1.5">
                  <label htmlFor="live-window-time-from" className="invisible px-1 text-[10px]">
                    From
                  </label>
                  <Input
                    type="time"
                    id="live-window-time-from"
                    aria-label="From time"
                    step={60}
                    value={toTimeStr(draft.from)}
                    onChange={(e) => {
                      const t = parseTime(e.target.value);
                      if (!t) return;
                      const next = new Date(draft.from);
                      next.setHours(t.hours, t.minutes, 0, 0);
                      setDraft((d) => {
                        const to = next > d.to
                          ? new Date(next.getTime() + 59_999)
                          : d.to;
                        return { from: next, to };
                      });
                    }}
                    className="h-8 bg-background text-[11px] mono appearance-none [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-calendar-picker-indicator]:appearance-none"
                  />
                </div>
              </div>

              {calTarget === "from" && (
                <div className="mt-2">
                  <Calendar
                    mode="single"
                    required
                    selected={draft.from}
                    onSelect={(day) => {
                      if (!day) return;
                      const next = new Date(day);
                      next.setHours(draft.from.getHours(), draft.from.getMinutes(), 0, 0);
                      setDraft((d) => {
                        const to = d.to < next
                          ? new Date(next.getTime() + 59_999)
                          : d.to;
                        return { from: next, to };
                      });
                      setCalTarget(null);
                    }}
                  />
                </div>
              )}

              {/* To row */}
              <div className="mt-2 flex gap-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <label className="px-1 text-[10px] text-muted-foreground">To date</label>
                  <Button
                    variant="outline"
                    className="h-8 w-full justify-between px-2 text-[11px] font-normal"
                    onClick={() => setCalTarget(calTarget === "to" ? null : "to")}
                  >
                    {formatDateBtn(draft.to)}
                    <ChevronDownIcon className="h-3 w-3 shrink-0 text-muted-foreground" />
                  </Button>
                </div>
                <div className="flex w-[122px] shrink-0 flex-col gap-1.5">
                  <label htmlFor="live-window-time-to" className="invisible px-1 text-[10px]">
                    To
                  </label>
                  <Input
                    type="time"
                    id="live-window-time-to"
                    aria-label="To time"
                    step={60}
                    value={toTimeStr(draft.to)}
                    onChange={(e) => {
                      const t = parseTime(e.target.value);
                      if (!t) return;
                      const next = new Date(draft.to);
                      next.setHours(t.hours, t.minutes, 59, 999);
                      setDraft((d) => {
                        const from = d.from > next
                          ? new Date(next.getTime() - 59_999)
                          : d.from;
                        return { from, to: next };
                      });
                    }}
                    className="h-8 bg-background text-[11px] mono appearance-none [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-calendar-picker-indicator]:appearance-none"
                  />
                </div>
              </div>

              {calTarget === "to" && (
                <div className="mt-2">
                  <Calendar
                    mode="single"
                    required
                    selected={draft.to}
                    onSelect={(day) => {
                      if (!day) return;
                      const next = new Date(day);
                      next.setHours(draft.to.getHours(), draft.to.getMinutes(), 59, 999);
                      setDraft((d) => {
                        const from = d.from > next
                          ? new Date(next.getTime() - 59_999)
                          : d.from;
                        return { from, to: next };
                      });
                      setCalTarget(null);
                    }}
                  />
                </div>
              )}

              <div className="mt-2 flex items-center justify-between gap-2">
                <Button
                  type="button"
                  size="xs"
                  variant="ghost"
                  className="h-7 px-2 text-[11px]"
                  onClick={() => {
                    setDraft(makeDraft("1h", undefined));
                    setCalTarget(null);
                  }}
                >
                  Reset
                </Button>
                <Button
                  type="button"
                  size="xs"
                  className="h-7 px-2 text-[11px]"
                  onClick={applyCustom}
                >
                  Apply Range
                </Button>
              </div>
            </div>

            <p className="text-[10px] text-muted-foreground/90">
              Selecting a window pauses live updates.
            </p>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
});
