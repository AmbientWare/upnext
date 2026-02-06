import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn, statusConfig, type JobStatus } from "@/lib/utils";
import { Panel } from "@/components/shared";
import { ChevronDown } from "lucide-react";
import { getJobTrends, queryKeys } from "@/lib/conduit-api";

type TimeRange = "24h" | "7d" | "30d";
type JobType = "all" | "cron" | "event" | "task";

interface TrendsPanelProps {
  className?: string;
}

const timeRangeOptions: { value: TimeRange; label: string; hours: number }[] = [
  { value: "24h", label: "24 Hours", hours: 24 },
  { value: "7d", label: "7 Days", hours: 168 },
  { value: "30d", label: "30 Days", hours: 168 }, // API max is 168
];

const jobTypeFilters: { value: JobType; label: string }[] = [
  { value: "all", label: "All Jobs" },
  { value: "cron", label: "Crons" },
  { value: "event", label: "Events" },
  { value: "task", label: "Tasks" },
];

// Status colors for the stacked bars
const stackedStatuses: JobStatus[] = ["complete", "failed", "cancelled", "retrying", "active", "queued", "pending"];

export function TrendsPanel({ className }: TrendsPanelProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [jobType, setJobType] = useState<JobType>("all");

  const hours = timeRangeOptions.find((t) => t.value === timeRange)?.hours ?? 24;

  const { data: trendsData } = useQuery({
    queryKey: queryKeys.jobTrends({ hours, type: jobType === "all" ? undefined : jobType }),
    queryFn: () => getJobTrends({ hours, type: jobType === "all" ? undefined : jobType }),
    refetchInterval: 30000, // Refresh every 30s
  });

  // Transform API data to chart format
  const data = (trendsData?.hourly ?? []).map((h) => ({
    label: new Date(h.hour).getHours().toString().padStart(2, "0") + ":00",
    statuses: {
      complete: h.complete,
      failed: h.failed,
      cancelled: h.cancelled,
      retrying: h.retrying,
      active: h.active,
      queued: h.queued,
      pending: h.pending,
    } as Record<JobStatus, number>,
  }));

  const maxTotal = Math.max(1, ...data.map((d) => Object.values(d.statuses).reduce((a, b) => a + b, 0)));

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
        </div>
      }
    >
      {/* Chart Area */}
      <div className="flex-1 relative min-h-[80px]">
        {data.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-[#555] text-xs">
            No job data available
          </div>
        ) : (
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
        )}
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
