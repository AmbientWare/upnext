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
  const streamWaiting = stats?.queue.waiting ?? 0;
  const claimed = stats?.queue.claimed ?? 0;
  const scheduledDue = stats?.queue.scheduled_due ?? 0;
  const scheduledFuture = stats?.queue.scheduled_future ?? 0;
  const backlog = stats?.queue.backlog ?? streamWaiting + claimed + scheduledDue;
  const capacity = stats?.queue.capacity ?? 0;
  const total = stats?.queue.total ?? 0;
  const utilization = capacity > 0 ? Math.min(running / capacity, 1) : 0;

  const animatedBacklog = useAnimatedNumber(backlog);
  const animatedTotal = useAnimatedNumber(total);
  const animatedStreamWaiting = useAnimatedNumber(streamWaiting);
  const animatedScheduledDue = useAnimatedNumber(scheduledDue);
  const animatedScheduledFuture = useAnimatedNumber(scheduledFuture);
  const animatedRunning = useAnimatedNumber(running);
  const animatedClaimed = useAnimatedNumber(claimed);
  const animatedCapacity = useAnimatedNumber(capacity);

  return (
    <Panel
      title="Job Queue"
      className={cn("h-full", className)}
      contentClassName="h-full px-3 py-2.5 flex flex-col gap-3"
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="mono text-3xl font-extrabold text-foreground">{animatedBacklog}</div>
          <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">Queue Length</div>
          <div className="mono text-xs text-muted-foreground mt-1">
            Total in system {animatedTotal}
          </div>
        </div>
        <div className="text-right">
          <div className="mono text-sm font-semibold text-muted-foreground">{Math.round(utilization * 100)}% utilized</div>
          <div className="mt-1.5 h-1.5 w-24 bg-muted rounded-full overflow-hidden ml-auto">
            <div
              className="h-full bg-cyan-400 transition-all duration-300"
              style={{ width: `${Math.round(utilization * 100)}%` }}
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div className="flex items-center justify-between rounded border border-input bg-muted/15 px-2.5 py-1.5">
          <span className="text-[11px] text-muted-foreground">Stream Waiting</span>
          <span className="mono text-[13px] font-medium text-foreground">{animatedStreamWaiting}</span>
        </div>
        <div className="flex items-center justify-between rounded border border-input bg-muted/15 px-2.5 py-1.5">
          <span className="text-[11px] text-muted-foreground">Scheduled Due</span>
          <span className="mono text-[13px] font-medium text-amber-400">{animatedScheduledDue}</span>
        </div>
        <div className="flex items-center justify-between rounded border border-input bg-muted/15 px-2.5 py-1.5">
          <span className="text-[11px] text-muted-foreground">Scheduled Future</span>
          <span className="mono text-[13px] font-medium text-muted-foreground">{animatedScheduledFuture}</span>
        </div>
        <div className="flex items-center justify-between rounded border border-input bg-muted/15 px-2.5 py-1.5">
          <span className="text-[11px] text-muted-foreground">Running</span>
          <span className="mono text-[13px] font-medium text-cyan-400">{animatedRunning}</span>
        </div>
      </div>

      <div className="mono text-[10px] text-muted-foreground/70 px-0.5">
        Claimed {animatedClaimed} · Capacity {animatedCapacity}
      </div>
    </Panel>
  );
}
