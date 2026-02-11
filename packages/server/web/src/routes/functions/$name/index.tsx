import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import type { DateRange } from "react-day-picker";
import { cn, formatNumber, formatDuration, formatTimeAgo, formatTimeUntil } from "@/lib/utils";
import { getFunction, getJobs, queryKeys } from "@/lib/upnext-api";
import type { FunctionType } from "@/lib/types";
import {
  Panel,
  JobsTablePanel,
  LiveWindowControls,
  getTimeWindowBounds,
  type TimeWindowPreset,
} from "@/components/shared";
import { FunctionDetailSkeleton } from "./-components/skeletons";
import {
  ArrowLeft,
  Circle,
  Clock,
  Repeat,
  Timer,
  Radio,
  CalendarClock,
  Users,
} from "lucide-react";
import { ConfigItem } from "./-components/config-item";
import { MetricCard } from "./-components/metric-card";
import { JobTrendsPanel } from "./-components/job-trends-panel";

export const Route = createFileRoute("/functions/$name/")({
  component: FunctionDetailPage,
});

const SAFETY_RESYNC_MS = 10 * 60 * 1000;
const LIVE_RESYNC_MS = 5 * 1000;
const LIVE_JOBS_LIMIT = 50;

const typeStyles: Record<FunctionType, string> = {
  task: "bg-blue-500/20 text-blue-400",
  cron: "bg-violet-500/20 text-violet-400",
  event: "bg-amber-500/20 text-amber-400",
};

const typeLabels: Record<FunctionType, string> = {
  task: "Task",
  cron: "Cron Job",
  event: "Event Handler",
};

function FunctionDetailPage() {
  const navigate = useNavigate();
  const { name } = Route.useParams();
  const decodedName = decodeURIComponent(name);
  const [jobsLive, setJobsLive] = useState(true);
  const [jobsWindowPreset, setJobsWindowPreset] = useState<TimeWindowPreset>("custom");
  const [jobsDateRange, setJobsDateRange] = useState<DateRange>();

  const jobsWindow = useMemo(() => {
    if (jobsLive) return null;
    return getTimeWindowBounds(jobsWindowPreset, jobsDateRange);
  }, [jobsDateRange, jobsLive, jobsWindowPreset]);

  const jobsQueryParams = useMemo(() => {
    if (jobsLive) {
      return { function: decodedName, limit: LIVE_JOBS_LIMIT };
    }

    if (!jobsWindow) {
      return { function: decodedName };
    }

    return {
      function: decodedName,
      after: jobsWindow.from.toISOString(),
      before: jobsWindow.to.toISOString(),
    };
  }, [decodedName, jobsLive, jobsWindow]);

  const jobsQueryKey = jobsLive
    ? queryKeys.jobs(jobsQueryParams)
    : (["jobs", "window", jobsQueryParams] as const);

  // Data fetching
  const { data: fn, isPending: isFunctionPending } = useQuery({
    queryKey: queryKeys.function(decodedName),
    queryFn: () => getFunction(decodedName),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const { data: jobsData, isPending: isJobsPending } = useQuery({
    queryKey: jobsQueryKey,
    queryFn: () => getJobs(jobsQueryParams),
    refetchInterval: jobsLive ? LIVE_RESYNC_MS : false,
    staleTime: jobsLive ? 0 : Number.POSITIVE_INFINITY,
  });

  const jobs = jobsData?.jobs ?? [];

  if (isFunctionPending && !fn) {
    return <FunctionDetailSkeleton />;
  }

  if (!fn) {
    return (
      <div className="p-4 h-full flex items-center justify-center text-muted-foreground text-sm">
        Function not found.
      </div>
    );
  }

  return (
    <div className="p-4 flex flex-col gap-3 h-full overflow-auto xl:overflow-hidden">
      {/* Back link + header */}
      <div className="shrink-0 flex flex-col gap-2">
        <Link
          to="/functions"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Functions
        </Link>

        <div className="flex items-center gap-3">
          <Circle
            className={cn(
              "w-2.5 h-2.5 shrink-0",
              fn.active ? "fill-emerald-400 text-emerald-400" : "fill-muted-foreground/60 text-muted-foreground/60"
            )}
          />
          <h2 className="mono text-lg font-semibold text-foreground">{fn.name}</h2>
          <span className={cn("text-[10px] px-2 py-0.5 rounded font-medium uppercase", typeStyles[fn.type])}>
            {fn.type}
          </span>
          <span className="text-xs text-muted-foreground">
            {fn.active ? "Active" : "Inactive"}
          </span>
        </div>
      </div>

      {/* Configuration + Metrics row */}
      <div className="grid grid-cols-1 2xl:grid-cols-2 gap-3 shrink-0">
        <Panel title={typeLabels[fn.type] + " Configuration"} className="flex-1" contentClassName="p-4">
          <div className="grid grid-cols-2 gap-x-8 gap-y-3">
            {fn.type === "task" && (
              <>
                <ConfigItem icon={Timer} label="Timeout" value={fn.timeout != null ? `${fn.timeout}s` : null} />
                <ConfigItem icon={Repeat} label="Max Retries" value={fn.max_retries != null ? String(fn.max_retries) : null} />
                <ConfigItem icon={Clock} label="Retry Delay" value={fn.retry_delay != null ? `${fn.retry_delay}s` : null} />
              </>
            )}

            {fn.type === "cron" && (
              <>
                <ConfigItem icon={CalendarClock} label="Schedule" value={fn.schedule} mono />
                <ConfigItem
                  icon={Clock}
                  label="Next Run"
                  value={fn.next_run_at ? formatTimeUntil(new Date(fn.next_run_at)) : null}
                />
                <ConfigItem icon={Timer} label="Timeout" value={fn.timeout != null ? `${fn.timeout}s` : null} />
              </>
            )}

            {fn.type === "event" && (
              <>
                <ConfigItem icon={Radio} label="Pattern" value={fn.pattern} mono />
                <ConfigItem icon={Timer} label="Timeout" value={fn.timeout != null ? `${fn.timeout}s` : null} />
                <ConfigItem icon={Repeat} label="Max Retries" value={fn.max_retries != null ? String(fn.max_retries) : null} />
                <ConfigItem icon={Clock} label="Retry Delay" value={fn.retry_delay != null ? `${fn.retry_delay}s` : null} />
              </>
            )}

            {/* Workers */}
            <div className="col-span-2">
              <div className="flex items-center gap-1.5 mb-1">
                <Users className="w-3 h-3 text-muted-foreground" />
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Workers</span>
              </div>
              {(fn.workers ?? []).length > 0 ? (
                <div className="flex items-center gap-1.5 flex-wrap">
                  {(fn.workers ?? []).map((w) => (
                    <span key={w} className="text-[10px] px-1.5 py-0.5 rounded bg-muted border border-input text-muted-foreground mono">
                      {w}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-xs text-muted-foreground/60">{"\u2014"}</span>
              )}
            </div>
          </div>
        </Panel>

        <Panel title="Metrics (24H)" className="flex-1" contentClassName="p-4">
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-4">
            <MetricCard label="Runs" value={formatNumber(fn.runs_24h)} />
            <MetricCard
              label="Success Rate"
              value={`${fn.success_rate.toFixed(1)}%`}
              color={fn.success_rate >= 99 ? "text-emerald-400" : fn.success_rate >= 95 ? "text-amber-400" : "text-red-400"}
            />
            <MetricCard label="Avg Duration" value={formatDuration(fn.avg_duration_ms)} />
            <MetricCard
              label="P95 Duration"
              value={fn.p95_duration_ms != null ? formatDuration(fn.p95_duration_ms) : "\u2014"}
            />
            <MetricCard
              label="Last Run"
              value={fn.last_run_at ? formatTimeAgo(new Date(fn.last_run_at)) : "\u2014"}
              sub={fn.last_run_status ?? undefined}
              animate={false}
            />
          </div>
        </Panel>
      </div>

      {/* Job Trends chart */}
      <JobTrendsPanel functionName={decodedName} />

      {/* Recent Jobs */}
      <JobsTablePanel
        jobs={jobs}
        hideFunction
        showFilters
        headerControls={
          <LiveWindowControls
            live={jobsLive}
            onLiveChange={setJobsLive}
            preset={jobsWindowPreset}
            onPresetChange={setJobsWindowPreset}
            dateRange={jobsDateRange}
            onDateRangeChange={setJobsDateRange}
          />
        }
        isLoading={isJobsPending}
        onJobClick={(job) => navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })}
      />
    </div>
  );
}
