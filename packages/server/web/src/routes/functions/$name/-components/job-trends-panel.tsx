import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type JobStatus } from "@/lib/utils";
import { getJobTrends, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { JobTrendsSnapshotEvent } from "@/lib/types";
import { Panel } from "@/components/shared";
import { BarChart4 } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

type TimeRange = "24h" | "7d";
type Granularity = "hourly" | "daily";

const timeRangeOptions: { value: TimeRange; label: string; hours: number }[] = [
  { value: "24h", label: "24 Hours", hours: 24 },
  { value: "7d", label: "7 Days", hours: 168 },
];

const chartConfig = {
  complete: { label: "Complete", color: "#10b981" },
  failed: { label: "Failed", color: "#ef4444" },
  retrying: { label: "Retrying", color: "#f97316" },
  active: { label: "Active", color: "#3b82f6" },
} satisfies ChartConfig;

const stackedStatuses: JobStatus[] = ["complete", "failed", "retrying", "active"];
const SAFETY_RESYNC_MS = 10 * 60 * 1000;

interface JobTrendsPanelProps {
  functionName: string;
  className?: string;
}

export function JobTrendsPanel({ functionName, className }: JobTrendsPanelProps) {
  const queryClient = useQueryClient();
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [granularity, setGranularity] = useState<Granularity>("hourly");

  const hours = timeRangeOptions.find((t) => t.value === timeRange)?.hours ?? 24;
  const trendsQueryKey = queryKeys.jobTrends({ hours, function: functionName });
  const params = new URLSearchParams({
    hours: String(hours),
    function: functionName,
  });
  const streamUrl = `${env.VITE_API_BASE_URL}/jobs/trends/stream?${params.toString()}`;

  const { data: trendsData } = useQuery({
    queryKey: trendsQueryKey,
    queryFn: () => getJobTrends({ hours, function: functionName }),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const handleTrendsStreamMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data) return;
      let payload: JobTrendsSnapshotEvent;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (payload.type !== "jobs.trends.snapshot") return;
      queryClient.setQueryData(trendsQueryKey, payload.trends);
    },
    [queryClient, trendsQueryKey]
  );

  useEventSource(streamUrl, {
    pauseWhenHidden: true,
    onMessage: handleTrendsStreamMessage,
  });

  const chartData = useMemo(() => {
    const hourly = trendsData?.hourly ?? [];
    if (granularity === "hourly") {
      return hourly.map((h) => ({
        label: new Date(h.hour).getHours().toString().padStart(2, "0") + ":00",
        complete: h.complete,
        failed: h.failed,
        retrying: h.retrying,
        active: h.active,
      }));
    }

    const byDay: Record<string, Record<string, number>> = {};
    for (const h of hourly) {
      const dayKey = h.hour.slice(0, 10);
      if (!byDay[dayKey]) {
        byDay[dayKey] = { complete: 0, failed: 0, retrying: 0, active: 0 };
      }
      byDay[dayKey].complete += h.complete;
      byDay[dayKey].failed += h.failed;
      byDay[dayKey].retrying += h.retrying;
      byDay[dayKey].active += h.active;
    }
    return Object.keys(byDay)
      .sort()
      .map((day) => ({
        label: new Date(day + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        ...byDay[day],
      }));
  }, [trendsData, granularity]);

  return (
    <Panel
      title="Job Trends"
      className={className ?? "shrink-0 h-56 flex flex-col overflow-hidden"}
      contentClassName="flex-1 flex flex-col overflow-hidden p-3"
      titleRight={
        <div className="flex items-center gap-2">
          <Select value={granularity} onValueChange={(v) => setGranularity(v as Granularity)}>
            <SelectTrigger size="sm" className="h-6 text-[10px] gap-1 px-2">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="hourly">Hourly</SelectItem>
              <SelectItem value="daily">Daily</SelectItem>
            </SelectContent>
          </Select>
          <Select value={timeRange} onValueChange={(v) => setTimeRange(v as TimeRange)}>
            <SelectTrigger size="sm" className="h-6 text-[10px] gap-1 px-2">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {timeRangeOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      }
    >
      <div className="flex-1 min-h-0">
        {chartData.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
            <div className="rounded-full bg-muted/60 p-2">
              <BarChart4 className="h-4 w-4" />
            </div>
            <div className="text-sm font-medium">No job data yet</div>
            <div className="text-xs text-muted-foreground/80">
              Trend activity will show up after runs start.
            </div>
          </div>
        ) : (
          <ChartContainer config={chartConfig} className="h-full w-full">
            <BarChart data={chartData}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                interval="preserveStartEnd"
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                width={30}
              />
              <ChartTooltip content={<ChartTooltipContent />} />
              {stackedStatuses.map((status) => (
                <Bar
                  key={status}
                  dataKey={status}
                  stackId="a"
                  fill={`var(--color-${status})`}
                  radius={status === "complete" ? [2, 2, 0, 0] : 0}
                  animationDuration={300}
                  animationEasing="ease-out"
                />
              ))}
            </BarChart>
          </ChartContainer>
        )}
      </div>
    </Panel>
  );
}
