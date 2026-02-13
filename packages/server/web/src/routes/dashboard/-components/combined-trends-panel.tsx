import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { BarChart4 } from "lucide-react";

import { cn, type JobStatus } from "@/lib/utils";
import { Panel } from "@/components/shared";
import { Skeleton } from "@/components/ui/skeleton";
import { getApiTrends, getJobTrends, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { ApiTrendsSnapshotEvent, JobTrendsSnapshotEvent } from "@/lib/types";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type ActiveTab = "jobs" | "apis";
type TimeRange = "24h" | "7d";
type JobType = "all" | "cron" | "event" | "task";
type Granularity = "hourly" | "daily";

interface CombinedTrendsPanelProps {
  className?: string;
}

const timeRangeOptions: { value: TimeRange; label: string; hours: number }[] = [
  { value: "24h", label: "24 Hours", hours: 24 },
  { value: "7d", label: "7 Days", hours: 168 },
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

const jobsChartConfig = {
  complete: { label: "Complete", color: "#10b981" },
  failed: { label: "Failed", color: "#ef4444" },
  retrying: { label: "Retrying", color: "#f97316" },
  active: { label: "Active", color: "#3b82f6" },
} satisfies ChartConfig;

const apisChartConfig = {
  "2xx": { label: "Success", color: "#10b981" },
  "4xx": { label: "Client Error", color: "#f59e0b" },
  "5xx": { label: "Server Error", color: "#ef4444" },
} satisfies ChartConfig;

const jobStackedStatuses: JobStatus[] = ["complete", "failed", "retrying", "active"];
const apiStackedStatuses = ["2xx", "4xx", "5xx"] as const;
const SAFETY_RESYNC_MS = 10 * 60 * 1000;

function EmptyChartState({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
      <div className="rounded-full bg-muted/60 p-2">
        <BarChart4 className="h-4 w-4" />
      </div>
      <div className="text-sm font-medium">{title}</div>
      <div className="text-xs text-muted-foreground/80">{subtitle}</div>
    </div>
  );
}

export function CombinedTrendsPanel({ className }: CombinedTrendsPanelProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<ActiveTab>("jobs");

  const [jobsTimeRange, setJobsTimeRange] = useState<TimeRange>("24h");
  const [jobsJobType, setJobsJobType] = useState<JobType>("all");
  const [jobsGranularity, setJobsGranularity] = useState<Granularity>("hourly");

  const [apisTimeRange, setApisTimeRange] = useState<TimeRange>("24h");
  const [apisGranularity, setApisGranularity] = useState<Granularity>("hourly");

  const jobsHours = timeRangeOptions.find((t) => t.value === jobsTimeRange)?.hours ?? 24;
  const jobsTypeFilter = jobsJobType === "all" ? undefined : jobsJobType;
  const jobsTrendsQueryKey = queryKeys.jobTrends({ hours: jobsHours, type: jobsTypeFilter });
  const jobsParams = new URLSearchParams({ hours: String(jobsHours) });
  if (jobsTypeFilter) jobsParams.set("type", jobsTypeFilter);
  const jobsStreamUrl = `${env.VITE_API_BASE_URL}/jobs/trends/stream?${jobsParams.toString()}`;

  const { data: jobsTrendsData, isPending: isJobsPending } = useQuery({
    queryKey: jobsTrendsQueryKey,
    queryFn: () => getJobTrends({ hours: jobsHours, type: jobsTypeFilter }),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const handleJobsStreamMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data) return;
      let payload: JobTrendsSnapshotEvent;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (payload.type !== "jobs.trends.snapshot") return;
      queryClient.setQueryData(jobsTrendsQueryKey, payload.trends);
    },
    [jobsTrendsQueryKey, queryClient]
  );

  useEventSource(jobsStreamUrl, {
    pauseWhenHidden: true,
    onMessage: handleJobsStreamMessage,
  });

  const jobsData = useMemo(() => {
    const hourly = jobsTrendsData?.hourly ?? [];
    if (jobsGranularity === "hourly") {
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
        label: new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        }),
        ...byDay[day],
      }));
  }, [jobsGranularity, jobsTrendsData]);

  const apisHours = timeRangeOptions.find((t) => t.value === apisTimeRange)?.hours ?? 24;
  const apisTrendsQueryKey = queryKeys.apiTrends({ hours: apisHours });
  const apisStreamUrl = `${env.VITE_API_BASE_URL}/apis/trends/stream?hours=${encodeURIComponent(String(apisHours))}`;

  const { data: apisTrendsData, isPending: isApisPending } = useQuery({
    queryKey: apisTrendsQueryKey,
    queryFn: () => getApiTrends({ hours: apisHours }),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const handleApisStreamMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data) return;
      let payload: ApiTrendsSnapshotEvent;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (payload.type !== "apis.trends.snapshot") return;
      queryClient.setQueryData(apisTrendsQueryKey, payload.trends);
    },
    [apisTrendsQueryKey, queryClient]
  );

  useEventSource(apisStreamUrl, {
    pauseWhenHidden: true,
    onMessage: handleApisStreamMessage,
  });

  const apisData = useMemo(() => {
    const hourly = apisTrendsData?.hourly ?? [];
    if (apisGranularity === "hourly") {
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
        label: new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        }),
        ...byDay[day],
      }));
  }, [apisGranularity, apisTrendsData]);

  const jobsControls = (
    <div className="flex items-center gap-2">
      <Select value={jobsJobType} onValueChange={(v) => setJobsJobType(v as JobType)}>
        <SelectTrigger size="sm" className="h-6 text-[10px] gap-1 px-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {jobTypeFilters.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={jobsGranularity} onValueChange={(v) => setJobsGranularity(v as Granularity)}>
        <SelectTrigger size="sm" className="h-6 text-[10px] gap-1 px-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {granularityOptions.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={jobsTimeRange} onValueChange={(v) => setJobsTimeRange(v as TimeRange)}>
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
  );

  const apisControls = (
    <div className="flex items-center gap-2">
      <Select value={apisGranularity} onValueChange={(v) => setApisGranularity(v as Granularity)}>
        <SelectTrigger size="sm" className="h-6 text-[10px] gap-1 px-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {granularityOptions.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={apisTimeRange} onValueChange={(v) => setApisTimeRange(v as TimeRange)}>
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
  );

  return (
    <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as ActiveTab)} className="h-full min-h-0">
      <Panel
        title="Trends"
        className={cn("h-full min-h-0 flex flex-col overflow-hidden", className)}
        contentClassName="flex-1 min-h-0 overflow-hidden p-0"
        titleCenter={(
          <TabsList variant="line" className="h-8">
            <TabsTrigger value="jobs" className="text-xs">Job Trends</TabsTrigger>
            <TabsTrigger value="apis" className="text-xs">API Trends</TabsTrigger>
          </TabsList>
        )}
        titleRight={activeTab === "jobs" ? jobsControls : apisControls}
      >
        <div className="border-b border-border" />

        <TabsContent value="jobs" className="h-full min-h-0 m-0 p-3">
          <div className="h-full min-h-0">
            {isJobsPending ? (
              <div className="h-full flex flex-col gap-3">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="flex-1 w-full" />
              </div>
            ) : jobsData.length === 0 ? (
              <EmptyChartState
                title="No job data yet"
                subtitle="Trends will appear once jobs start running."
              />
            ) : (
              <ChartContainer config={jobsChartConfig} className="h-full w-full">
                <BarChart data={jobsData}>
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
                  {jobStackedStatuses.map((status) => (
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
        </TabsContent>

        <TabsContent value="apis" className="h-full min-h-0 m-0 p-3">
          <div className="h-full min-h-0">
            {isApisPending ? (
              <div className="h-full flex flex-col gap-3">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="flex-1 w-full" />
              </div>
            ) : apisData.length === 0 ? (
              <EmptyChartState
                title="No API data yet"
                subtitle="Trends will populate after API traffic begins."
              />
            ) : (
              <ChartContainer config={apisChartConfig} className="h-full w-full">
                <BarChart data={apisData}>
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
                  {apiStackedStatuses.map((status) => (
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
        </TabsContent>
      </Panel>
    </Tabs>
  );
}
