import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { BackLink, DetailPageLayout, MetricPill, Panel, ProgressBar, StatusDot, TypeBadge } from "@/components/shared";
import { getWorkers, queryKeys } from "@/lib/upnext-api";
import type { WorkerInfo } from "@/lib/types";
import { cn, formatNumber, formatTimeAgo } from "@/lib/utils";

export const Route = createFileRoute("/workers/$name/")({
  component: WorkerDetailPage,
});

const WORKERS_LIVE_RESYNC_MS = 10 * 1000;

type WorkerFunction = {
  key: string;
  name: string;
};

function getWorkerFunctions(worker: WorkerInfo): WorkerFunction[] {
  const byKey = new Map<string, string>();

  for (const fnKey of worker.functions) {
    byKey.set(fnKey, worker.function_names?.[fnKey] ?? fnKey);
  }

  for (const instance of worker.instances) {
    for (const fnKey of instance.functions) {
      byKey.set(fnKey, instance.function_names?.[fnKey] ?? byKey.get(fnKey) ?? fnKey);
    }
  }

  return Array.from(byKey.entries())
    .map(([key, name]) => ({ key, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function CapacityDonut({ active, total }: { active: number; total: number }) {
  const safeTotal = Math.max(total, 0);
  const safeActive = Math.max(active, 0);
  const percent = safeTotal > 0 ? Math.min((safeActive / safeTotal) * 100, 100) : 0;
  const ringColor =
    percent >= 90 ? "#ef4444" : percent >= 70 ? "#f59e0b" : percent >= 40 ? "#22d3ee" : "#10b981";

  const size = 80;
  const strokeWidth = 8;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (circumference * percent) / 100;

  return (
    <div className="flex flex-col items-center justify-center gap-1.5">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          className="text-muted/40"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={ringColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text
          x="50%"
          y="50%"
          textAnchor="middle"
          dominantBaseline="middle"
          className="mono text-[11px] fill-foreground"
        >
          {`${Math.round(percent)}%`}
        </text>
      </svg>
      <span className="text-[9px] uppercase tracking-wider text-muted-foreground/70">Utilization</span>
    </div>
  );
}

function WorkerDetailPage() {
  const { name } = Route.useParams();
  const decodedName = decodeURIComponent(name);
  const [, setClockMs] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockMs(Date.now());
    }, 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: WORKERS_LIVE_RESYNC_MS,
    staleTime: 0,
  });

  const worker = useMemo(
    () => data?.workers.find((candidate) => candidate.name === decodedName || candidate.name === name),
    [data?.workers, decodedName, name]
  );

  const functions = useMemo(() => (worker ? getWorkerFunctions(worker) : []), [worker]);

  const stats = useMemo(() => {
    if (!worker) {
      return {
        totalConcurrency: 0,
        activeJobs: 0,
        jobsProcessed: 0,
        jobsFailed: 0,
        lastHeartbeat: null as Date | null,
      };
    }

    const activeJobs = worker.instances.reduce((sum, instance) => sum + instance.active_jobs, 0);
    const totalConcurrencyFromInstances = worker.instances.reduce(
      (sum, instance) => sum + instance.concurrency,
      0
    );
    const totalConcurrency =
      totalConcurrencyFromInstances > 0 ? totalConcurrencyFromInstances : Math.max(worker.concurrency, activeJobs);
    const jobsProcessed = worker.instances.reduce((sum, instance) => sum + instance.jobs_processed, 0);
    const jobsFailed = worker.instances.reduce((sum, instance) => sum + instance.jobs_failed, 0);

    let lastHeartbeat: Date | null = null;
    for (const instance of worker.instances) {
      const next = new Date(instance.last_heartbeat);
      if (Number.isNaN(next.getTime())) continue;
      if (!lastHeartbeat || next > lastHeartbeat) {
        lastHeartbeat = next;
      }
    }

    return { totalConcurrency, activeJobs, jobsProcessed, jobsFailed, lastHeartbeat };
  }, [worker]);

  if (isPending) {
    return <div className="p-4 text-sm text-muted-foreground">Loading worker metrics...</div>;
  }

  if (error) {
    return <div className="p-4 text-sm text-red-400">Failed to load worker metrics.</div>;
  }

  if (!worker) {
    return (
      <div className="p-4 h-full flex flex-col gap-3">
        <BackLink to="/workers" label="Workers" />
        <div className="text-sm text-muted-foreground">Worker not found.</div>
      </div>
    );
  }

  const failRate = stats.jobsProcessed + stats.jobsFailed > 0
    ? (stats.jobsFailed / (stats.jobsProcessed + stats.jobsFailed)) * 100
    : 0;

  return (
    <DetailPageLayout>
      {/* ─── Header (compact) ─── */}
      <div className="shrink-0 space-y-1.5">
        <BackLink to="/workers" label="Workers" />

        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5 min-w-0">
            <StatusDot active={worker.active} />
            <h2 className="mono text-lg font-semibold text-foreground truncate">{worker.name}</h2>
            <TypeBadge label="Worker" color="cyan" />
            {!worker.active && (
              <span className="text-[10px] text-muted-foreground/60 uppercase">Inactive</span>
            )}
          </div>

          {stats.lastHeartbeat && (
            <span className="text-[11px] text-muted-foreground shrink-0 hidden sm:inline">
              Last heartbeat {formatTimeAgo(stats.lastHeartbeat)}
            </span>
          )}
        </div>

        {/* Metrics strip */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <MetricPill
            label="Instances"
            value={`${worker.instances.length}/${Math.max(worker.instance_count, worker.instances.length)}`}
          />
          <MetricPill label="Functions" value={String(functions.length)} />
          <MetricPill label="Running" value={String(stats.activeJobs)} tone="text-cyan-300" />
          <MetricPill label="Capacity" value={String(stats.totalConcurrency)} />
          <MetricPill label="Completed" value={formatNumber(stats.jobsProcessed)} />
          <MetricPill
            label="Failed"
            value={formatNumber(stats.jobsFailed)}
            tone={stats.jobsFailed > 0 ? "text-red-400" : undefined}
          />
          {failRate > 0 && (
            <MetricPill
              label="Fail Rate"
              value={`${failRate.toFixed(1)}%`}
              tone={failRate > 5 ? "text-red-400" : failRate > 1 ? "text-amber-400" : undefined}
            />
          )}
        </div>
      </div>

      {/* ─── Capacity + Functions (capacity determines row height) ─── */}
      <div className="shrink-0 flex flex-col xl:flex-row gap-3">
        <Panel
          title="Capacity"
          className="xl:w-48 xl:shrink-0"
          contentClassName="px-3 py-2.5 flex items-center justify-center"
        >
          <CapacityDonut active={stats.activeJobs} total={stats.totalConcurrency} />
        </Panel>

        <div className="h-48 xl:h-auto xl:flex-1 xl:min-w-0 relative">
          <div className="absolute inset-0">
            <Panel
              title={`Functions (${functions.length})`}
              className="h-full flex flex-col overflow-hidden"
              contentClassName="p-2 flex-1 min-h-0 overflow-hidden"
            >
              {functions.length === 0 ? (
                <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
                  No functions currently assigned
                </div>
              ) : (
                <div className="flex flex-wrap gap-1.5 h-full overflow-y-auto pr-1 overscroll-contain content-start">
                  {functions.map((fn) => (
                    <Link
                      key={fn.key}
                      to="/functions/$name"
                      params={{ name: fn.key }}
                      className="inline-flex items-center gap-1.5 rounded border border-input bg-muted/30 px-2 py-1 hover:bg-accent transition-colors"
                    >
                      <span className="text-[11px] text-foreground truncate" title={fn.name}>
                        {fn.name}
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        </div>
      </div>

      {/* ─── Instances ─── */}
      <Panel
        title={`Instances (${worker.instances.length})`}
        className="flex-1 min-h-0 flex flex-col overflow-hidden"
        contentClassName="p-2 flex-1 min-h-0 overflow-hidden"
      >
        {worker.instances.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
            No active instances
          </div>
        ) : (
          <div className="space-y-2 h-full overflow-y-auto pr-1 overscroll-contain">
            {worker.instances.map((instance) => (
              <div key={instance.id} className="rounded border border-input bg-muted/30 px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="mono text-[11px] text-foreground">{instance.id}</span>
                  <span className="text-[10px] text-muted-foreground">
                    {formatTimeAgo(new Date(instance.last_heartbeat))}
                  </span>
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  <ProgressBar
                    value={instance.active_jobs}
                    max={instance.concurrency}
                    color="auto"
                    className="w-20"
                  />
                  <span className="mono text-[10px] text-muted-foreground">
                    {instance.active_jobs}/{instance.concurrency}
                  </span>
                  {instance.hostname ? (
                    <span className="mono text-[10px] text-muted-foreground/80 truncate">
                      {instance.hostname}
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 flex items-center gap-3 mono text-[10px] text-muted-foreground">
                  <span>done {formatNumber(instance.jobs_processed)}</span>
                  <span className={cn(instance.jobs_failed > 0 ? "text-red-400" : "text-muted-foreground")}>
                    failed {formatNumber(instance.jobs_failed)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </DetailPageLayout>
  );
}
