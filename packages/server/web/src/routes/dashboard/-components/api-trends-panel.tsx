import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";
import { ChevronDown } from "lucide-react";
import { getApiTrends, queryKeys } from "@/lib/conduit-api";

type TimeRange = "24h" | "7d" | "30d";

interface ApiTrendsPanelProps {
  className?: string;
}

const timeRangeOptions: { value: TimeRange; label: string }[] = [
  { value: "24h", label: "24 Hours" },
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
];

type ApiStatus = "2xx" | "4xx" | "5xx";

const apiStatusConfig: Record<ApiStatus, { label: string; color: string }> = {
  "2xx": { label: "Success", color: "bg-emerald-500" },
  "4xx": { label: "Client Error", color: "bg-amber-500" },
  "5xx": { label: "Server Error", color: "bg-red-500" },
};

const stackedStatuses: ApiStatus[] = ["2xx", "4xx", "5xx"];

// Convert time range to hours for API
function timeRangeToHours(range: TimeRange): number {
  switch (range) {
    case "24h": return 24;
    case "7d": return 24 * 7;
    case "30d": return 24 * 30;
  }
}

export function ApiTrendsPanel({ className }: ApiTrendsPanelProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");

  const hours = timeRangeToHours(timeRange);

  // Fetch API trends data
  const { data: trendsData } = useQuery({
    queryKey: queryKeys.apiTrends({ hours }),
    queryFn: () => getApiTrends({ hours }),
    refetchInterval: 30000, // Refresh every 30s
  });

  // Transform API data to chart format
  const data = useMemo(() => {
    if (!trendsData?.hourly) {
      return [];
    }
    return trendsData.hourly.map((h) => {
      const date = new Date(h.hour);
      return {
        label: date.getHours().toString().padStart(2, "0") + ":00",
        statuses: {
          "2xx": h.success_2xx,
          "4xx": h.client_4xx,
          "5xx": h.server_5xx,
        } as Record<ApiStatus, number>,
      };
    });
  }, [trendsData]);

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
