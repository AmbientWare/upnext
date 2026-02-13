import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import type { DateRange } from "react-day-picker";
import { toast } from "sonner";
import { cn, formatNumber, formatDuration, formatTimeAgo, formatTimeUntil } from "@/lib/utils";
import {
  cancelJob,
  getFunction,
  getJobs,
  pauseFunction,
  queryKeys,
  resumeFunction,
  retryJob,
} from "@/lib/upnext-api";
import type { FunctionType } from "@/lib/types";
import {
  Panel,
  MetricPill,
  BackLink,
  StatusDot,
  TypeBadge,
  DetailPageLayout,
  JobsTablePanel,
  LiveWindowControls,
  getTimeWindowBounds,
  LIVE_LIST_LIMIT,
  LIVE_REFRESH_INTERVAL_MS,
  type TimeWindowPreset,
} from "@/components/shared";
import { FunctionDetailSkeleton } from "./-components/skeletons";
import {
  Clock,
  Repeat,
  Timer,
  Radio,
  CalendarClock,
  Users,
  Pause,
  Play,
  RotateCcw,
  X,
} from "lucide-react";
import { ConfigItem } from "./-components/config-item";
import { JobTrendsPanel } from "./-components/job-trends-panel";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/functions/$name/")({
  component: FunctionDetailPage,
});

const SAFETY_RESYNC_MS = 10 * 60 * 1000;

const typeConfig: Record<FunctionType, { label: string; color: "blue" | "violet" | "amber" }> = {
  task: { label: "Task", color: "blue" },
  cron: { label: "Cron", color: "violet" },
  event: { label: "Event", color: "amber" },
};

const RETRYABLE_STATUSES = new Set(["failed", "cancelled"]);
const CANCELLABLE_STATUSES = new Set(["pending", "queued", "active", "retrying"]);

function FunctionDetailPage() {
  const queryClient = useQueryClient();
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
      return { function: decodedName, limit: LIVE_LIST_LIMIT };
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

  const { data: fn, isPending: isFunctionPending } = useQuery({
    queryKey: queryKeys.function(decodedName),
    queryFn: () => getFunction(decodedName),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const { data: jobsData, isPending: isJobsPending } = useQuery({
    queryKey: jobsQueryKey,
    queryFn: () => getJobs(jobsQueryParams),
    refetchInterval: jobsLive ? LIVE_REFRESH_INTERVAL_MS : false,
    staleTime: jobsLive ? 0 : Number.POSITIVE_INFINITY,
  });

  const jobs = jobsData?.jobs ?? [];

  const togglePauseMutation = useMutation({
    mutationFn: (isPaused: boolean) =>
      isPaused ? resumeFunction(decodedName) : pauseFunction(decodedName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.function(decodedName) });
      queryClient.invalidateQueries({ queryKey: ["functions"] });
    },
    onError: (error: unknown) => {
      toast.error(error instanceof Error ? error.message : "Failed to update pause state");
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.function(decodedName) });
    },
    onError: (error: unknown) => {
      toast.error(error instanceof Error ? error.message : "Failed to cancel job");
    },
  });

  const retryMutation = useMutation({
    mutationFn: (jobId: string) => retryJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.function(decodedName) });
    },
    onError: (error: unknown) => {
      toast.error(error instanceof Error ? error.message : "Failed to retry job");
    },
  });

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

  const dispatchTotal =
    fn.dispatch_reasons.paused +
    fn.dispatch_reasons.rate_limited +
    fn.dispatch_reasons.no_capacity +
    fn.dispatch_reasons.cancelled +
    fn.dispatch_reasons.retrying;

  return (
    <DetailPageLayout>
      {/* ─── Header (compact) ─── */}
      <div className="shrink-0 space-y-1.5">
        <BackLink to="/functions" label="Functions" />

        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5 min-w-0">
            <StatusDot active={fn.active} />
            <h2 className="mono text-lg font-semibold text-foreground truncate">{fn.name}</h2>
            <TypeBadge label={typeConfig[fn.type].label} color={typeConfig[fn.type].color} />
            {!fn.active && (
              <span className="text-[10px] text-muted-foreground/60 uppercase">Inactive</span>
            )}
            {fn.paused && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium uppercase shrink-0">
                Paused
              </span>
            )}
            <Button
              size="xs"
              variant="outline"
              disabled={togglePauseMutation.isPending}
              onClick={() => togglePauseMutation.mutate(fn.paused)}
            >
              {fn.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
              {fn.paused ? "Resume" : "Pause"}
            </Button>
          </div>

          {fn.last_run_at && (
            <span className="text-[11px] text-muted-foreground shrink-0 hidden sm:inline">
              Last run {formatTimeAgo(new Date(fn.last_run_at))}
              {fn.last_run_status && (
                <span
                  className={cn(
                    "ml-1",
                    fn.last_run_status === "complete"
                      ? "text-emerald-400"
                      : fn.last_run_status === "failed"
                        ? "text-red-400"
                        : "text-muted-foreground"
                  )}
                >
                  · {fn.last_run_status}
                </span>
              )}
            </span>
          )}
        </div>

        {/* Metrics strip */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <MetricPill label="Runs 24h" value={formatNumber(fn.runs_24h)} />
          <MetricPill
            label="Success"
            value={`${fn.success_rate.toFixed(1)}%`}
            tone={
              fn.success_rate >= 99
                ? "text-emerald-400"
                : fn.success_rate >= 95
                  ? "text-amber-400"
                  : "text-red-400"
            }
          />
          <MetricPill label="Avg" value={formatDuration(fn.avg_duration_ms)} />
          <MetricPill
            label="P95"
            value={fn.p95_duration_ms != null ? formatDuration(fn.p95_duration_ms) : "\u2014"}
          />
          <MetricPill
            label="Wait"
            value={fn.avg_wait_ms != null ? formatDuration(fn.avg_wait_ms) : "\u2014"}
          />
          <MetricPill
            label="P95 Wait"
            value={fn.p95_wait_ms != null ? formatDuration(fn.p95_wait_ms) : "\u2014"}
          />
          <MetricPill label="Backlog" value={formatNumber(fn.queue_backlog)} />
          {dispatchTotal > 0 && (
            <MetricPill label="Blocked" value={formatNumber(dispatchTotal)} tone="text-amber-400" />
          )}
        </div>
      </div>

      {/* ─── Config + Trends (config determines row height) ─── */}
      <div className="shrink-0 flex flex-col xl:flex-row gap-3">
        <Panel
          title={typeConfig[fn.type].label + " Configuration"}
          className="xl:w-80 xl:shrink-0"
          contentClassName="px-3 py-2.5"
        >
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            {fn.type === "task" && (
              <>
                <ConfigItem icon={Timer} label="Timeout" value={fn.timeout != null ? `${fn.timeout}s` : null} />
                <ConfigItem icon={Repeat} label="Retries" value={fn.max_retries != null ? String(fn.max_retries) : null} />
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
                <ConfigItem icon={Repeat} label="Retries" value={fn.max_retries != null ? String(fn.max_retries) : null} />
                <ConfigItem icon={Clock} label="Retry Delay" value={fn.retry_delay != null ? `${fn.retry_delay}s` : null} />
              </>
            )}
          </div>

          {/* Workers */}
          <div className="mt-2.5 pt-2.5 border-t border-input/60">
            <div className="flex items-center gap-1.5 mb-1">
              <Users className="w-3 h-3 text-muted-foreground" />
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Workers</span>
            </div>
            {(fn.workers ?? []).length > 0 ? (
              <div className="flex items-center gap-1 flex-wrap">
                {(fn.workers ?? []).map((w) => (
                  <span
                    key={w}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-muted border border-input text-muted-foreground mono"
                  >
                    {w}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-xs text-muted-foreground/60">{"\u2014"}</span>
            )}
          </div>

          {/* Dispatch blocks — only when non-zero */}
          {dispatchTotal > 0 && (
            <div className="mt-2.5 pt-2.5 border-t border-input/60">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
                Dispatch Blocks
              </span>
              <div className="mt-1 flex items-center gap-3 flex-wrap text-[11px]">
                {fn.dispatch_reasons.paused > 0 && (
                  <span className="text-amber-400/80 flex items-center gap-0.5">
                    <Pause className="w-3 h-3" />
                    {fn.dispatch_reasons.paused} paused
                  </span>
                )}
                {fn.dispatch_reasons.rate_limited > 0 && (
                  <span className="text-amber-400/80 flex items-center gap-0.5">
                    <Clock className="w-3 h-3" />
                    {fn.dispatch_reasons.rate_limited} rate limited
                  </span>
                )}
                {fn.dispatch_reasons.no_capacity > 0 && (
                  <span className="text-amber-400/80 flex items-center gap-0.5">
                    <Users className="w-3 h-3" />
                    {fn.dispatch_reasons.no_capacity} no capacity
                  </span>
                )}
                {fn.dispatch_reasons.cancelled > 0 && (
                  <span className="text-zinc-400 flex items-center gap-0.5">
                    <X className="w-3 h-3" />
                    {fn.dispatch_reasons.cancelled} cancelled
                  </span>
                )}
                {fn.dispatch_reasons.retrying > 0 && (
                  <span className="text-orange-400 flex items-center gap-0.5">
                    <RotateCcw className="w-3 h-3" />
                    {fn.dispatch_reasons.retrying} retrying
                  </span>
                )}
              </div>
            </div>
          )}
        </Panel>

        <div className="h-56 xl:h-auto xl:flex-1 xl:min-w-0 relative">
          <div className="absolute inset-0">
            <JobTrendsPanel
              functionName={decodedName}
              className="h-full flex flex-col overflow-hidden"
            />
          </div>
        </div>
      </div>

      {/* ─── Recent Jobs ─── */}
      <JobsTablePanel
        jobs={jobs}
        hideFunction
        showFilters
        className="flex-1 min-h-0 flex flex-col overflow-hidden"
        renderActions={(job) => (
          <div className="inline-flex items-center gap-1">
            {RETRYABLE_STATUSES.has(job.status) ? (
              <Button
                size="xs"
                variant="ghost"
                disabled={retryMutation.isPending}
                onClick={() => retryMutation.mutate(job.id)}
                aria-label={`Retry ${job.id}`}
                title="Retry"
              >
                <RotateCcw className="h-3 w-3" />
              </Button>
            ) : null}
            {CANCELLABLE_STATUSES.has(job.status) ? (
              <Button
                size="xs"
                variant="ghost"
                disabled={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate(job.id)}
                aria-label={`Cancel ${job.id}`}
                title="Cancel"
              >
                <X className="h-3 w-3" />
              </Button>
            ) : null}
          </div>
        )}
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
    </DetailPageLayout>
  );
}
