import { Panel } from "@/components/shared";
import type { DashboardStats } from "@/lib/types";
import { cn, formatDateTime, formatDuration } from "@/lib/utils";

interface RunbookPanelsProps {
  stats: DashboardStats | undefined;
  isPending?: boolean;
  className?: string;
  onFunctionClick?: (key: string) => void;
  onJobClick?: (jobId: string) => void;
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="h-full min-h-[160px] flex items-center justify-center text-xs text-muted-foreground">
      {label}
    </div>
  );
}

function formatAge(seconds: number): string {
  return formatDuration(Math.max(0, seconds) * 1000);
}

export function RunbookPanels({
  stats,
  isPending = false,
  className,
  onFunctionClick,
  onJobClick,
}: RunbookPanelsProps) {
  const failing = stats?.top_failing_functions ?? [];
  const oldest = stats?.oldest_queued_jobs ?? [];
  const stuck = stats?.stuck_active_jobs ?? [];

  return (
    <div className={cn("grid grid-cols-1 xl:grid-cols-3 gap-3", className)}>
      <Panel
        title="Top Failing Functions"
        titleRight={(
          <a
            href="/docs"
            className="text-[10px] text-muted-foreground hover:text-foreground underline"
          >
            Dispatch Reason Docs
          </a>
        )}
        contentClassName="p-0"
      >
        {isPending ? (
          <EmptyState label="Loading runbook data..." />
        ) : failing.length === 0 ? (
          <EmptyState label="No failing functions in the last 24h." />
        ) : (
          <div className="max-h-56 overflow-auto">
            {failing.map((item) => (
              <button
                key={item.key}
                type="button"
                className="w-full text-left px-3 py-2 border-b border-border/60 hover:bg-accent/40 last:border-b-0"
                onClick={() => onFunctionClick?.(item.key)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="mono text-[11px] text-foreground truncate">{item.name}</span>
                  <span className="mono text-[11px] text-red-400">{item.failure_rate.toFixed(1)}%</span>
                </div>
                <div className="mono text-[10px] text-muted-foreground mt-1">
                  {item.failures_24h}/{item.runs_24h} failed
                  {item.last_run_at ? ` • ${formatDateTime(new Date(item.last_run_at))}` : ""}
                </div>
              </button>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Oldest Queued Jobs" contentClassName="p-0">
        {isPending ? (
          <EmptyState label="Loading runbook data..." />
        ) : oldest.length === 0 ? (
          <EmptyState label="No queued jobs." />
        ) : (
          <div className="max-h-56 overflow-auto">
            {oldest.map((item) => (
              <button
                key={`${item.source}:${item.id}`}
                type="button"
                className="w-full text-left px-3 py-2 border-b border-border/60 hover:bg-accent/40 last:border-b-0"
                onClick={() => onJobClick?.(item.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="mono text-[11px] text-foreground truncate">{item.function_name}</span>
                  <span className="mono text-[11px] text-amber-400">{formatAge(item.age_seconds)}</span>
                </div>
                <div className="mono text-[10px] text-muted-foreground mt-1">
                  {item.id} • {item.source} • {formatDateTime(new Date(item.queued_at))}
                </div>
              </button>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Stuck Active Jobs" contentClassName="p-0">
        {isPending ? (
          <EmptyState label="Loading runbook data..." />
        ) : stuck.length === 0 ? (
          <EmptyState label="No stuck active jobs." />
        ) : (
          <div className="max-h-56 overflow-auto">
            {stuck.map((item) => (
              <button
                key={item.id}
                type="button"
                className="w-full text-left px-3 py-2 border-b border-border/60 hover:bg-accent/40 last:border-b-0"
                onClick={() => onJobClick?.(item.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="mono text-[11px] text-foreground truncate">{item.function_name}</span>
                  <span className="mono text-[11px] text-red-400">{formatAge(item.age_seconds)}</span>
                </div>
                <div className="mono text-[10px] text-muted-foreground mt-1">
                  {item.id}
                  {item.worker_id ? ` • ${item.worker_id}` : ""}
                  {` • ${formatDateTime(new Date(item.started_at))}`}
                </div>
              </button>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
