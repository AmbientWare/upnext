import { Panel } from "@/components/shared";
import { useAnimatedNumber } from "@/hooks/use-animated-number";
import type { DashboardStats } from "@/lib/types";
import { cn } from "@/lib/utils";

interface QueueStatsPanelProps {
  stats: DashboardStats | undefined;
  className?: string;
}

export function QueueStatsPanel({ stats, className }: QueueStatsPanelProps) {
  const running = stats?.queue.running ?? 0;
  const waiting = stats?.queue.waiting ?? 0;
  const claimed = stats?.queue.claimed ?? 0;
  const capacity = stats?.queue.capacity ?? 0;
  const total = stats?.queue.total ?? 0;
  const utilization = capacity > 0 ? Math.min(running / capacity, 1) : 0;

  const animatedTotal = useAnimatedNumber(total);
  const animatedWaiting = useAnimatedNumber(waiting);
  const animatedRunning = useAnimatedNumber(running);
  const animatedClaimed = useAnimatedNumber(claimed);
  const animatedCapacity = useAnimatedNumber(capacity);

  return (
    <Panel
      title="Job Queue"
      className={cn("h-full", className)}
      contentClassName="h-full p-4 flex flex-col gap-3"
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="mono text-3xl font-bold text-foreground">{animatedTotal}</div>
          <div className="text-xs text-muted-foreground uppercase tracking-wider mt-1">Total Jobs</div>
        </div>
        <div className="text-right">
          <div className="mono text-sm text-muted-foreground">{Math.round(utilization * 100)}% utilized</div>
          <div className="mt-2 h-1.5 w-20 bg-muted rounded-full overflow-hidden ml-auto">
            <div
              className="h-full bg-cyan-400 transition-all duration-300"
              style={{ width: `${Math.round(utilization * 100)}%` }}
            />
          </div>
        </div>
      </div>

      <div className="space-y-2 text-sm">
        <div className="flex items-center justify-between rounded border border-border/60 px-2 py-1.5">
          <span className="text-muted-foreground">Waiting</span>
          <span className="mono text-foreground">{animatedWaiting}</span>
        </div>
        <div className="flex items-center justify-between rounded border border-border/60 px-2 py-1.5">
          <span className="text-muted-foreground">Running</span>
          <span className="mono text-cyan-400">{animatedRunning}</span>
        </div>
        <div className="mono text-[10px] text-muted-foreground px-1 pt-0.5">
          Claimed {animatedClaimed} • Capacity {animatedCapacity}
        </div>
      </div>
    </Panel>
  );
}
