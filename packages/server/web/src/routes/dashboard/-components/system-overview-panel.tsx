import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";
import type { DashboardStats, WorkerInfo } from "@/lib/types";
import { useAnimatedNumber } from "@/hooks/use-animated-number";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type OverviewWindow = "1m" | "5m" | "15m" | "1h" | "24h";

const WINDOW_OPTIONS: Array<{ value: OverviewWindow; label: string }> = [
  { value: "1m", label: "1 Minute" },
  { value: "5m", label: "5 Minutes" },
  { value: "15m", label: "15 Minutes" },
  { value: "1h", label: "1 Hour" },
  { value: "24h", label: "24 Hours" },
];

interface SystemOverviewPanelProps {
  stats: DashboardStats | undefined;
  workers: WorkerInfo[];
  window: OverviewWindow;
  onWindowChange: (next: OverviewWindow) => void;
  className?: string;
}

function windowLabel(window: OverviewWindow): string {
  const match = WINDOW_OPTIONS.find((opt) => opt.value === window);
  return match?.label ?? "Window";
}

export function SystemOverviewPanel({
  stats,
  workers,
  window,
  onWindowChange,
  className,
}: SystemOverviewPanelProps) {
  const activeWorkers = workers.filter((w) => w.active);
  const activeCount = activeWorkers.length;

  // Worker aggregates (from live instances)
  const allInstances = activeWorkers.flatMap((w) => w.instances);
  const totalCapacity = allInstances.reduce((sum, inst) => sum + inst.concurrency, 0);
  const totalActive = allInstances.reduce((sum, inst) => sum + inst.active_jobs, 0);

  // Windowed metrics
  const throughput = stats?.runs.jobs_per_min ?? 0;
  const throughputStr = throughput >= 1000 ? `${(throughput / 1000).toFixed(1)}K` : `${throughput}`;
  const successRate = stats?.runs.success_rate ?? 0;
  const windowText = windowLabel(window);

  // API aggregates (same selected window)
  const totalReqPerMin = stats?.apis.requests_per_min ?? 0;
  const avgLatency = stats?.apis.avg_latency_ms ?? 0;
  const errorRate = stats?.apis.error_rate ?? 0;

  const animatedWorkers = useAnimatedNumber(activeCount);
  const animatedUtilActive = useAnimatedNumber(totalActive);
  const animatedUtilCapacity = useAnimatedNumber(totalCapacity);
  const animatedThroughput = useAnimatedNumber(throughputStr);
  const animatedSuccessRate = useAnimatedNumber(`${successRate.toFixed(1)}%`);
  const animatedApiReqs = useAnimatedNumber(
    totalReqPerMin >= 1000 ? `${(totalReqPerMin / 1000).toFixed(1)}K` : `${totalReqPerMin}`
  );
  const animatedLatency = useAnimatedNumber(Math.round(avgLatency));
  const animatedErrorRate = useAnimatedNumber(`${errorRate.toFixed(1)}%`);

  return (
    <Panel
      title="System Overview"
      titleRight={(
        <Select value={window} onValueChange={(v) => onWindowChange(v as OverviewWindow)}>
          <SelectTrigger size="sm" className="h-6 w-[118px] text-[10px] gap-1 px-2">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {WINDOW_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      className={className}
      contentClassName="p-5"
    >
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-6">
        {/* Workers - with load bar */}
        <div>
          <div className={cn("mono text-3xl font-bold", activeCount > 0 ? "text-foreground" : "text-muted-foreground")}>
            {animatedWorkers}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Active Workers</div>
          <div className="mono text-xs text-muted-foreground mt-1">
            Utilization {animatedUtilActive}/{animatedUtilCapacity}
          </div>
        </div>

        {/* Throughput */}
        <div>
          <div className="mono text-3xl font-bold text-foreground">{animatedThroughput}</div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">
            Jobs / Min ({windowText})
          </div>
        </div>

        {/* Success Rate */}
        <div>
          <div className={cn(
            "mono text-3xl font-bold",
            successRate >= 99 ? "text-emerald-400" : successRate >= 95 ? "text-amber-400" : "text-red-400"
          )}>
            {animatedSuccessRate}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">
            Job Success Rate ({windowText})
          </div>
        </div>

        {/* API Req/min */}
        <div>
          <div className="mono text-3xl font-bold text-foreground">
            {animatedApiReqs}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">
            API Requests / Min ({windowText})
          </div>
        </div>

        {/* API Latency */}
        <div>
          <div className={cn(
            "mono text-3xl font-bold",
            avgLatency < 100 ? "text-emerald-400" : avgLatency < 500 ? "text-amber-400" : "text-red-400"
          )}>
            {animatedLatency}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">
            API Avg Latency (ms, {windowText})
          </div>
        </div>

        {/* Error Rate */}
        <div>
          <div className={cn(
            "mono text-3xl font-bold",
            errorRate < 1 ? "text-emerald-400" : errorRate < 5 ? "text-amber-400" : "text-red-400"
          )}>
            {animatedErrorRate}
          </div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">
            API Error Rate ({windowText})
          </div>
        </div>
      </div>
    </Panel>
  );
}
