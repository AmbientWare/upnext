import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { type JobStatus } from "@/lib/utils";
import { getJobTrends, queryKeys } from "@/lib/conduit-api";
import { Panel } from "@/components/shared";
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

interface JobTrendsPanelProps {
  functionName: string;
  className?: string;
}

export function JobTrendsPanel({ functionName, className }: JobTrendsPanelProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [granularity, setGranularity] = useState<Granularity>("hourly");

  const hours = timeRangeOptions.find((t) => t.value === timeRange)?.hours ?? 24;

  const { data: trendsData } = useQuery({
    queryKey: queryKeys.jobTrends({ hours, function: functionName }),
    queryFn: () => getJobTrends({ hours, function: functionName }),
    refetchInterval: 30000,
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
          <div className="h-full flex items-center justify-center text-muted-foreground text-xs">
            No job data available
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
                />
              ))}
            </BarChart>
          </ChartContainer>
        )}
      </div>
    </Panel>
  );
}
