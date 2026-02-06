import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";
import type { DashboardStats, WorkerInfo, ApiInfo } from "@/lib/types";

interface SystemOverviewPanelProps {
  stats: DashboardStats | undefined;
  workers: WorkerInfo[];
  apis: ApiInfo[];
  className?: string;
}

export function SystemOverviewPanel({ stats, workers, apis, className }: SystemOverviewPanelProps) {
  const activeWorkers = workers.filter((w) => w.active);
  const activeCount = activeWorkers.length;

  // Worker aggregates (from live instances)
  const allInstances = activeWorkers.flatMap((w) => w.instances);
  const totalCapacity = allInstances.reduce((sum, inst) => sum + inst.concurrency, 0);
  const totalActive = allInstances.reduce((sum, inst) => sum + inst.active_jobs, 0);
  const loadPct = totalCapacity > 0 ? Math.round((totalActive / totalCapacity) * 100) : 0;

  // Job metrics
  const throughput = stats ? Math.round(stats.runs.total_24h / 1440) : 0;
  const throughputStr = throughput >= 1000 ? `${(throughput / 1000).toFixed(1)}K` : `${throughput}`;
  const activeJobs = stats?.runs.active_count ?? 0;
  const successRate = stats?.runs.success_rate ?? 0;

  // API aggregates
  const totalReqPerMin = apis.reduce((sum, a) => sum + a.requests_per_min, 0);
  const avgLatency = stats?.apis.avg_latency_ms ?? 0;
  const errorRate = stats?.apis.error_rate ?? 0;

  return (
    <Panel
      title="System Overview"
      className={className}
      contentClassName="p-5"
    >
      <div className="grid grid-cols-4 gap-6">
        {/* Workers - with load bar */}
        <div>
          <div className={cn("mono text-3xl font-bold", activeCount > 0 ? "text-foreground" : "text-muted-foreground")}>
            {activeCount}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Workers</div>
          <div className="mono text-xs text-muted-foreground mt-1">{loadPct}% load</div>
        </div>

        {/* Throughput */}
        <div>
          <div className="mono text-3xl font-bold text-foreground">{throughputStr}</div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Jobs/min</div>
        </div>

        {/* Active Jobs */}
        <div>
          <div className="mono text-3xl font-bold text-foreground">{activeJobs}</div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Active Jobs</div>
        </div>

        {/* Success Rate */}
        <div>
          <div className={cn(
            "mono text-3xl font-bold",
            successRate >= 99 ? "text-emerald-400" : successRate >= 95 ? "text-amber-400" : "text-red-400"
          )}>
            {successRate.toFixed(1)}%
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Success Rate</div>
        </div>

        {/* API Req/min */}
        <div>
          <div className="mono text-3xl font-bold text-foreground">
            {totalReqPerMin >= 1000 ? `${(totalReqPerMin / 1000).toFixed(1)}K` : totalReqPerMin}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">API Req/min</div>
        </div>

        {/* API Latency */}
        <div>
          <div className={cn(
            "mono text-3xl font-bold",
            avgLatency < 100 ? "text-emerald-400" : avgLatency < 500 ? "text-amber-400" : "text-red-400"
          )}>
            {Math.round(avgLatency)}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Latency (ms)</div>
        </div>

        {/* Error Rate */}
        <div>
          <div className={cn(
            "mono text-3xl font-bold",
            errorRate < 1 ? "text-emerald-400" : errorRate < 5 ? "text-amber-400" : "text-red-400"
          )}>
            {errorRate.toFixed(1)}%
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Error Rate</div>
        </div>
      </div>
    </Panel>
  );
}
