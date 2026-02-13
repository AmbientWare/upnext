import { Panel } from "@/components/shared";
import { Separator } from "@/components/ui/separator";
import { StatusBadge } from "@/components/shared/status-badge";
import { formatDuration } from "@/lib/utils";
import type { Job } from "@/lib/types";

interface JobDetailsPanelProps {
  job: Job;
}

interface StatRowProps {
  label: string;
  value: string;
  valueClassName?: string;
}

function JsonBlock({ value, emptyLabel = "—" }: { value: unknown; emptyLabel?: string }) {
  if (!value || (typeof value === "object" && Object.keys(value as object).length === 0)) {
    return <span className="text-xs text-muted-foreground">{emptyLabel}</span>;
  }

  return (
    <div className="max-w-full overflow-hidden rounded border border-input bg-muted/30">
      <div className="max-w-full overflow-x-auto">
        <pre className="mono inline-block min-w-full p-2 text-[10px] leading-relaxed whitespace-pre">
          {JSON.stringify(value, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function StatRow({ label, value, valueClassName }: StatRowProps) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-x-3">
      <span className="text-muted-foreground">{label}</span>
      <span className={`mono min-w-0 break-words ${valueClassName ?? ""}`}>
        {value}
      </span>
    </div>
  );
}

export function JobDetailsPanel({ job }: JobDetailsPanelProps) {
  const startedLabel = job.started_at ? new Date(job.started_at).toLocaleString() : "—";
  const completedLabel = job.completed_at ? new Date(job.completed_at).toLocaleString() : "—";

  return (
    <Panel
      title="Job Details"
      className="h-full flex flex-col overflow-hidden"
      contentClassName="flex-1 overflow-hidden p-0"
    >
      <div className="h-full overflow-y-auto">
        <div className="p-3 pr-4 space-y-4">
          <div className="space-y-1.5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Task</div>
            <div className="mono text-xs break-all">{job.function_name || job.function}</div>
            <div className="mono text-[10px] text-muted-foreground break-all">{job.id}</div>
          </div>

          <div className="flex items-center justify-between gap-3">
            <StatusBadge status={job.status} />
            <span className="mono text-[10px] text-muted-foreground shrink-0">
              {job.duration_ms ? formatDuration(job.duration_ms) : "—"}
            </span>
          </div>

          <Separator />

          <div className="space-y-2 text-[11px]">
            <StatRow label="Worker" value={job.worker_id ?? "—"} />
            <StatRow label="Attempts" value={`${job.attempts}/${job.max_retries + 1}`} />
            <StatRow label="Progress" value={`${Math.round((job.progress ?? 0) * 100)}%`} />
            <StatRow label="Started" value={startedLabel} />
            <StatRow label="Completed" value={completedLabel} />
          </div>

          <Separator />

          <div className="space-y-1.5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Checkpoint</div>
            <JsonBlock value={job.checkpoint} emptyLabel="No checkpoint" />
          </div>

          <div className="space-y-1.5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Arguments</div>
            <JsonBlock value={job.kwargs} emptyLabel="No arguments" />
          </div>

          {job.error && (
            <div className="space-y-1.5">
              <div className="text-[10px] uppercase tracking-wider text-red-400">Error</div>
              <pre className="mono text-[10px] leading-relaxed bg-red-500/10 border border-red-500/30 rounded p-2 overflow-auto whitespace-pre-wrap break-all">
                {job.error}
              </pre>
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
