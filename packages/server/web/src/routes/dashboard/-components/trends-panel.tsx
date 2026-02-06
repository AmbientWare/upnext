import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { cn, type JobStatus } from "@/lib/utils";
import { Panel } from "@/components/shared";
import { ChevronDown } from "lucide-react";
import { getJobTrends, queryKeys } from "@/lib/conduit-api";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

type TimeRange = "24h" | "7d" | "30d";
type JobType = "all" | "cron" | "event" | "task";
type Granularity = "hourly" | "daily";

interface TrendsPanelProps {
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

const jobTypeFilters: { value: JobType; label: string }[] = [
  { value: "all", label: "All Jobs" },
  { value: "cron", label: "Crons" },
  { value: "event", label: "Events" },
  { value: "task", label: "Tasks" },
];

const chartConfig = {
  complete: { label: "Complete", color: "#10b981" },
  failed: { label: "Failed", color: "#ef4444" },
  retrying: { label: "Retrying", color: "#f97316" },
  active: { label: "Active", color: "#3b82f6" },
} satisfies ChartConfig;

const stackedStatuses: JobStatus[] = ["complete", "failed", "retrying", "active"];

export function TrendsPanel({ className }: TrendsPanelProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [jobType, setJobType] = useState<JobType>("all");
  const [granularity, setGranularity] = useState<Granularity>("hourly");

  const hours = timeRangeOptions.find((t) => t.value === timeRange)?.hours ?? 24;

  const { data: trendsData } = useQuery({
    queryKey: queryKeys.jobTrends({ hours, type: jobType === "all" ? undefined : jobType }),
    queryFn: () => getJobTrends({ hours, type: jobType === "all" ? undefined : jobType }),
    refetchInterval: 30000,
  });

  const data = useMemo(() => {
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
      className={cn("flex-1 flex flex-col overflow-hidden", className)}
      contentClassName="flex-1 flex flex-col overflow-hidden p-3"
      titleRight={
        <div className="flex items-center gap-2">
          <FilterSelect value={jobType} onChange={(v) => setJobType(v as JobType)} options={jobTypeFilters} />
          <FilterSelect value={granularity} onChange={(v) => setGranularity(v as Granularity)} options={granularityOptions} />
          <FilterSelect value={timeRange} onChange={(v) => setTimeRange(v as TimeRange)} options={timeRangeOptions} />
        </div>
      }
    >
      <div className="flex-1 min-h-0">
        {data.length === 0 ? (
          <div className="h-full flex items-center justify-center text-[#555] text-xs">
            No job data available
          </div>
        ) : (
          <ChartContainer config={chartConfig} className="h-full w-full">
            <BarChart data={data}>
              <CartesianGrid vertical={false} stroke="#1e1e1e" />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tick={{ fill: "#555", fontSize: 10 }}
                interval="preserveStartEnd"
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                tick={{ fill: "#555", fontSize: 10 }}
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

function FilterSelect({ value, onChange, options }: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded px-2 py-1 pr-6 text-[10px] text-[#888] focus:outline-none"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 w-3 h-3 text-[#555] pointer-events-none" />
    </div>
  );
}
