import { useMemo, useState } from "react";
import { cn, statusConfig, type JobStatus } from "@/lib/utils";
import { Panel } from "@/components/shared";
import { ChevronDown } from "lucide-react";

type TimeRange = "24h" | "7d" | "30d";
type Interval = "hour" | "day";
type JobType = "all" | "cron" | "event" | "task";

interface TrendsPanelProps {
  className?: string;
}

const timeRangeOptions: { value: TimeRange; label: string }[] = [
  { value: "24h", label: "24 Hours" },
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
];

const intervalOptions: { value: Interval; label: string }[] = [
  { value: "hour", label: "Hourly" },
  { value: "day", label: "Daily" },
];

const jobTypeFilters: { value: JobType; label: string }[] = [
  { value: "all", label: "All Jobs" },
  { value: "cron", label: "Crons" },
  { value: "event", label: "Events" },
  { value: "task", label: "Tasks" },
];

// Status colors for the stacked bars
const stackedStatuses: JobStatus[] = ["complete", "failed", "cancelled", "retrying", "active", "queued", "pending"];

function generateTrendData(range: TimeRange, interval: Interval, jobType: JobType) {
  const now = new Date();
  const data: { label: string; statuses: Record<JobStatus, number> }[] = [];

  let buckets: number;
  if (range === "24h") {
    buckets = interval === "hour" ? 24 : 1;
  } else if (range === "7d") {
    buckets = interval === "hour" ? 24 * 7 : 7;
  } else {
    buckets = interval === "hour" ? 24 * 30 : 30;
  }

  // Limit to reasonable number of bars
  const maxBars = interval === "hour" ? 24 : 30;
  buckets = Math.min(buckets, maxBars);

  // Multiplier based on job type (simulate filtering)
  const multiplier = jobType === "all" ? 1 : jobType === "cron" ? 0.4 : jobType === "event" ? 0.35 : 0.25;

  for (let i = buckets - 1; i >= 0; i--) {
    const date = new Date(now);
    if (interval === "hour") {
      date.setHours(date.getHours() - i);
      data.push({
        label: date.getHours().toString().padStart(2, "0") + ":00",
        statuses: {
          complete: Math.floor((Math.floor(Math.random() * 80) + 20) * multiplier),
          failed: Math.floor(Math.floor(Math.random() * 10) * multiplier),
          cancelled: Math.floor(Math.floor(Math.random() * 5) * multiplier),
          retrying: Math.floor(Math.floor(Math.random() * 8) * multiplier),
          active: Math.floor(Math.floor(Math.random() * 15) * multiplier),
          queued: Math.floor(Math.floor(Math.random() * 20) * multiplier),
          pending: Math.floor(Math.floor(Math.random() * 10) * multiplier),
        },
      });
    } else {
      date.setDate(date.getDate() - i);
      const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
      data.push({
        label: dayNames[date.getDay()],
        statuses: {
          complete: Math.floor((Math.floor(Math.random() * 500) + 200) * multiplier),
          failed: Math.floor(Math.floor(Math.random() * 50) * multiplier),
          cancelled: Math.floor(Math.floor(Math.random() * 25) * multiplier),
          retrying: Math.floor(Math.floor(Math.random() * 40) * multiplier),
          active: Math.floor(Math.floor(Math.random() * 80) * multiplier),
          queued: Math.floor(Math.floor(Math.random() * 100) * multiplier),
          pending: Math.floor(Math.floor(Math.random() * 50) * multiplier),
        },
      });
    }
  }

  return data;
}

export function TrendsPanel({ className }: TrendsPanelProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [interval, setInterval] = useState<Interval>("hour");
  const [jobType, setJobType] = useState<JobType>("all");

  const data = useMemo(() => generateTrendData(timeRange, interval, jobType), [timeRange, interval, jobType]);

  const maxTotal = useMemo(() => {
    return Math.max(...data.map((d) => Object.values(d.statuses).reduce((a, b) => a + b, 0)));
  }, [data]);

  return (
    <Panel
      title="Job Trends"
      className={cn("flex-1 flex flex-col overflow-hidden", className)}
      contentClassName="flex-1 flex flex-col overflow-hidden p-3"
      titleRight={
        <div className="flex items-center gap-2">
          {/* Job Type Selector */}
          <div className="relative">
            <select
              value={jobType}
              onChange={(e) => setJobType(e.target.value as JobType)}
              className="appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 pr-6 text-[10px] text-[#888] focus:outline-none"
            >
              {jobTypeFilters.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-[#555] pointer-events-none" />
          </div>

          {/* Time Range Selector */}
          <div className="relative">
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value as TimeRange)}
              className="appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 pr-6 text-[10px] text-[#888] focus:outline-none"
            >
              {timeRangeOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-[#555] pointer-events-none" />
          </div>

          {/* Interval Selector */}
          <div className="relative">
            <select
              value={interval}
              onChange={(e) => setInterval(e.target.value as Interval)}
              className="appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 pr-6 text-[10px] text-[#888] focus:outline-none"
            >
              {intervalOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-[#555] pointer-events-none" />
          </div>
        </div>
      }
    >
      {/* Chart Area */}
      <div className="flex-1 relative min-h-[80px]">
        <div className="absolute inset-0 flex items-end gap-1 pb-4">
          {data.map((bucket, i) => {
            const total = Object.values(bucket.statuses).reduce((a, b) => a + b, 0);
            const barHeight = maxTotal > 0 ? (total / maxTotal) * 100 : 0;

            return (
              <div key={i} className="flex-1 flex flex-col items-center min-w-0 h-full">
                {/* Stacked Bar */}
                <div className="flex-1 w-full flex items-end">
                  <div
                    className="w-full flex flex-col-reverse rounded-t overflow-hidden"
                    style={{ height: `${Math.max(barHeight, 4)}%` }}
                  >
                    {stackedStatuses.map((status) => {
                      const count = bucket.statuses[status];
                      const statusPercent = total > 0 ? (count / total) * 100 : 0;
                      if (statusPercent === 0) return null;
                      return (
                        <div
                          key={status}
                          className={cn("w-full transition-all", statusConfig[status].dot)}
                          style={{ height: `${statusPercent}%` }}
                          title={`${statusConfig[status].label}: ${count}`}
                        />
                      );
                    })}
                  </div>
                </div>
                {/* Label */}
                <span className="text-[8px] text-[#555] truncate w-full text-center pt-1 shrink-0">{bucket.label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 py-2 border-t border-[#2a2a2a] flex-wrap">
        {stackedStatuses.slice(0, 4).map((status) => (
          <div key={status} className="flex items-center gap-1">
            <div className={cn("w-2 h-2 rounded-sm", statusConfig[status].dot)} />
            <span className="text-[9px] text-[#666]">{statusConfig[status].label}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
