import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";
import { Skeleton } from "@/components/ui/skeleton";
import { getApiTrends, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { ApiTrendsSnapshotEvent } from "@/lib/types";
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

type TimeRange = "24h" | "7d" | "30d";
type Granularity = "hourly" | "daily";

interface ApiTrendsPanelProps {
  className?: string;
}

const timeRangeOptions: { value: TimeRange; label: string; hours: number }[] = [
  { value: "24h", label: "24 Hours", hours: 24 },
  { value: "7d", label: "7 Days", hours: 168 },
  { value: "30d", label: "30 Days", hours: 168 }, // API max is 168
];

const granularityOptions: { value: Granularity; label: string }[] = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
];

const chartConfig = {
  "2xx": { label: "Success", color: "#10b981" },
  "4xx": { label: "Client Error", color: "#f59e0b" },
  "5xx": { label: "Server Error", color: "#ef4444" },
} satisfies ChartConfig;

const stackedStatuses = ["2xx", "4xx", "5xx"] as const;
const SAFETY_RESYNC_MS = 10 * 60 * 1000;

export function ApiTrendsPanel({ className }: ApiTrendsPanelProps) {
  const queryClient = useQueryClient();
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [granularity, setGranularity] = useState<Granularity>("hourly");

  const hours = timeRangeOptions.find((t) => t.value === timeRange)?.hours ?? 24;
  const trendsQueryKey = queryKeys.apiTrends({ hours });
  const streamUrl = `${env.VITE_API_BASE_URL}/apis/trends/stream?hours=${encodeURIComponent(String(hours))}`;

  const { data: trendsData, isPending } = useQuery({
    queryKey: trendsQueryKey,
    queryFn: () => getApiTrends({ hours }),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const handleTrendsStreamMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data) return;
      let payload: ApiTrendsSnapshotEvent;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (payload.type !== "apis.trends.snapshot") return;
      queryClient.setQueryData(trendsQueryKey, payload.trends);
    },
    [queryClient, trendsQueryKey]
  );

  useEventSource(streamUrl, {
    pauseWhenHidden: true,
    onMessage: handleTrendsStreamMessage,
  });

  const data = useMemo(() => {
    const hourly = trendsData?.hourly ?? [];
    if (granularity === "hourly") {
      return hourly.map((h) => ({
        label: new Date(h.hour).getHours().toString().padStart(2, "0") + ":00",
        "2xx": h.success_2xx,
        "4xx": h.client_4xx,
        "5xx": h.server_5xx,
      }));
    }

    const byDay: Record<string, Record<string, number>> = {};
    for (const h of hourly) {
      const dayKey = h.hour.slice(0, 10);
      if (!byDay[dayKey]) {
        byDay[dayKey] = { "2xx": 0, "4xx": 0, "5xx": 0 };
      }
      byDay[dayKey]["2xx"] += h.success_2xx;
      byDay[dayKey]["4xx"] += h.client_4xx;
      byDay[dayKey]["5xx"] += h.server_5xx;
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
      title="API Trends"
      className={cn("flex-1 flex flex-col overflow-hidden", className)}
      contentClassName="flex-1 flex flex-col overflow-hidden p-3"
      titleRight={
        <div className="flex items-center gap-2">
          <Select value={granularity} onValueChange={(v) => setGranularity(v as Granularity)}>
            <SelectTrigger size="sm" className="h-6 text-[10px] gap-1 px-2">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {granularityOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
              ))}
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
        {isPending ? (
          <div className="h-full flex flex-col gap-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="flex-1 w-full" />
          </div>
        ) : data.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
            <div className="rounded-full bg-muted/60 p-2">
              <BarChart4 className="h-4 w-4" />
            </div>
            <div className="text-sm font-medium">No API data yet</div>
            <div className="text-xs text-muted-foreground/80">
              Trends will populate after API traffic begins.
            </div>
          </div>
        ) : (
          <ChartContainer config={chartConfig} className="h-full w-full">
            <BarChart data={data}>
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
                  radius={status === "2xx" ? [2, 2, 0, 0] : 0}
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
