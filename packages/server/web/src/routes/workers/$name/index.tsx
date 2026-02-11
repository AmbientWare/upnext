import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Circle } from "lucide-react";

import { MetricTile, Panel, ProgressBar } from "@/components/shared";
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

  const size = 112;
  const strokeWidth = 12;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (circumference * percent) / 100;

  return (
    <div className="flex flex-col items-center justify-center gap-2">
      <span className="mono text-sm text-foreground">
        {safeActive}/{safeTotal}
      </span>
      <div className="relative">
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
            className="mono text-[12px] fill-foreground"
          >
            {`${Math.round(percent)}%`}
          </text>
        </svg>
      </div>
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Capacity Used</span>
    </div>
  );
}

function WorkerDetailPage() {
  const { name } = Route.useParams();
  const decodedName = decodeURIComponent(name);
  const [, setClockMs] = useState(() => Date.now());

  // Keep "x ago" labels ticking even between server updates.
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
        <Link
          to="/workers"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Workers
        </Link>
        <div className="text-sm text-muted-foreground">Worker not found.</div>
      </div>
    );
  }

  return (
    <div className="p-4 h-full overflow-auto xl:overflow-hidden flex flex-col gap-4">
      <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-wrap">
        <Link
          to="/workers"
          className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Workers
        </Link>
        <span className="text-muted-foreground/60">/</span>
        <h2 className="text-lg font-semibold text-foreground truncate">{worker.name}</h2>
        <Circle
          className={cn(
            "w-2 h-2 shrink-0",
            worker.active ? "fill-emerald-400 text-emerald-400" : "fill-muted-foreground/60 text-muted-foreground/60"
          )}
        />
      </div>

      <Panel title="Worker Overview" className="shrink-0" contentClassName="p-3 sm:p-4">
        <div className="grid grid-cols-1 xl:grid-cols-[140px_1fr] gap-4 items-center">
          <CapacityDonut active={stats.activeJobs} total={stats.totalConcurrency} />
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
            <MetricTile
              label="Instances"
              value={`${worker.instances.length}/${Math.max(worker.instance_count, worker.instances.length)}`}
            />
            <MetricTile label="Functions" value={`${functions.length}`} />
            <MetricTile label="Active Jobs" value={`${stats.activeJobs}`} tone="text-cyan-300" />
            <MetricTile label="Processed Jobs" value={formatNumber(stats.jobsProcessed)} />
            <MetricTile
              label="Failed Jobs"
              value={formatNumber(stats.jobsFailed)}
              tone={stats.jobsFailed > 0 ? "text-red-400" : "text-muted-foreground"}
            />
            <MetricTile
              label="Last Heartbeat"
              value={stats.lastHeartbeat ? formatTimeAgo(stats.lastHeartbeat) : "—"}
            />
          </div>
        </div>
      </Panel>

      <div className="grid grid-cols-1 xl:grid-cols-2 xl:grid-rows-[minmax(0,1fr)] gap-3 flex-1 min-h-0">
        <Panel
          title={`Functions (${functions.length})`}
          className="h-full min-h-0 flex flex-col overflow-hidden"
          contentClassName="p-2 flex-1 min-h-0 overflow-hidden"
        >
          {functions.length === 0 ? (
            <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
              No functions currently assigned
            </div>
          ) : (
            <div className="space-y-1.5 h-full overflow-y-auto pr-1 overscroll-contain">
              {functions.map((fn) => (
                <Link
                  key={fn.key}
                  to="/functions/$name"
                  params={{ name: fn.key }}
                  className="block rounded border border-input bg-muted/30 px-2.5 py-2 hover:bg-accent transition-colors overflow-hidden"
                >
                  <div className="text-xs text-foreground truncate" title={fn.name}>
                    {fn.name}
                  </div>
                  <div className="mono text-[10px] text-muted-foreground truncate" title={fn.key}>
                    {fn.key}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </Panel>

        <Panel
          title={`Instances (${worker.instances.length})`}
          className="h-full min-h-0 flex flex-col overflow-hidden"
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
      </div>
    </div>
  );
}
