import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";
import { ChevronDown } from "lucide-react";

type TimeRange = "24h" | "7d" | "30d";
type Interval = "hour" | "day";

interface ApiTrendsPanelProps {
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

type ApiStatus = "2xx" | "4xx" | "5xx";

const apiStatusConfig: Record<ApiStatus, { label: string; color: string }> = {
  "2xx": { label: "Success", color: "bg-emerald-500" },
  "4xx": { label: "Client Error", color: "bg-amber-500" },
  "5xx": { label: "Server Error", color: "bg-red-500" },
};

const stackedStatuses: ApiStatus[] = ["2xx", "4xx", "5xx"];

function generateApiTrendData(range: TimeRange, interval: Interval) {
  const now = new Date();
  const data: { label: string; statuses: Record<ApiStatus, number> }[] = [];

  let buckets: number;
  if (range === "24h") {
    buckets = interval === "hour" ? 24 : 1;
  } else if (range === "7d") {
    buckets = interval === "hour" ? 24 * 7 : 7;
  } else {
    buckets = interval === "hour" ? 24 * 30 : 30;
  }

  const maxBars = interval === "hour" ? 24 : 30;
  buckets = Math.min(buckets, maxBars);

  for (let i = buckets - 1; i >= 0; i--) {
    const date = new Date(now);
    if (interval === "hour") {
      date.setHours(date.getHours() - i);
      data.push({
        label: date.getHours().toString().padStart(2, "0") + ":00",
        statuses: {
          "2xx": Math.floor(Math.random() * 500) + 200,
          "4xx": Math.floor(Math.random() * 30) + 5,
          "5xx": Math.floor(Math.random() * 10),
        },
      });
    } else {
      date.setDate(date.getDate() - i);
      const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
      data.push({
        label: dayNames[date.getDay()],
        statuses: {
          "2xx": Math.floor(Math.random() * 5000) + 2000,
          "4xx": Math.floor(Math.random() * 300) + 50,
          "5xx": Math.floor(Math.random() * 100),
        },
      });
    }
  }

  return data;
}

export function ApiTrendsPanel({ className }: ApiTrendsPanelProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [interval, setInterval] = useState<Interval>("hour");

  const data = useMemo(() => generateApiTrendData(timeRange, interval), [timeRange, interval]);

  const maxTotal = useMemo(() => {
    return Math.max(...data.map((d) => Object.values(d.statuses).reduce((a, b) => a + b, 0)));
  }, [data]);

  // Calculate totals for summary
  const totals = useMemo(() => {
    return data.reduce(
      (acc, d) => ({
        "2xx": acc["2xx"] + d.statuses["2xx"],
        "4xx": acc["4xx"] + d.statuses["4xx"],
        "5xx": acc["5xx"] + d.statuses["5xx"],
      }),
      { "2xx": 0, "4xx": 0, "5xx": 0 }
    );
  }, [data]);

  const totalRequests = totals["2xx"] + totals["4xx"] + totals["5xx"];
  const errorRate = totalRequests > 0 ? (((totals["4xx"] + totals["5xx"]) / totalRequests) * 100).toFixed(1) : "0";

  return (
    <Panel
      title="API Trends"
      className={cn("flex-1 flex flex-col overflow-hidden", className)}
      contentClassName="flex-1 flex flex-col overflow-hidden p-3"
      titleRight={
        <div className="flex items-center gap-2">
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
                          className={cn("w-full transition-all", apiStatusConfig[status].color)}
                          style={{ height: `${statusPercent}%` }}
                          title={`${apiStatusConfig[status].label}: ${count}`}
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

      {/* Legend & Stats */}
      <div className="flex items-center justify-between py-2 border-t border-[#2a2a2a]">
        <div className="flex items-center gap-3">
          {stackedStatuses.map((status) => (
            <div key={status} className="flex items-center gap-1">
              <div className={cn("w-2 h-2 rounded-sm", apiStatusConfig[status].color)} />
              <span className="text-[9px] text-[#666]">{apiStatusConfig[status].label}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 text-[9px]">
          <span className="text-[#666]">
            Total: <span className="text-[#999] mono">{totalRequests.toLocaleString()}</span>
          </span>
          <span className="text-[#666]">
            Error Rate: <span className={cn("mono", Number(errorRate) > 5 ? "text-red-400" : "text-[#999]")}>{errorRate}%</span>
          </span>
        </div>
      </div>
    </Panel>
  );
}
