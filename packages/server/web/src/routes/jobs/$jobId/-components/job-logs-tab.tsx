import { useMemo, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { TreeJob } from "./timeline-model";

interface JobLogsTabProps {
  jobs: TreeJob[];
  selectedJobId: string;
}

type LogScope = "all" | "selected";

interface LogEntry {
  id: string;
  jobId: string;
  timestamp: number;
  level: "info" | "error";
  message: string;
}

function toEntries(jobs: TreeJob[]): LogEntry[] {
  const entries: LogEntry[] = [];

  for (const job of jobs) {
    const label = `${job.function_name || job.function} (${job.id.slice(0, 8)})`;
    const createdAt = job.created_at ? new Date(job.created_at).getTime() : NaN;
    const startedAt = job.started_at ? new Date(job.started_at).getTime() : NaN;
    const completedAt = job.completed_at ? new Date(job.completed_at).getTime() : NaN;

    if (Number.isFinite(createdAt)) {
      entries.push({
        id: `${job.id}-created`,
        jobId: job.id,
        timestamp: createdAt,
        level: "info",
        message: `${label} queued`,
      });
    }
    if (Number.isFinite(startedAt)) {
      entries.push({
        id: `${job.id}-started`,
        jobId: job.id,
        timestamp: startedAt,
        level: "info",
        message: `${label} started`,
      });
    }
    if (Number.isFinite(completedAt)) {
      entries.push({
        id: `${job.id}-end`,
        jobId: job.id,
        timestamp: completedAt,
        level: job.status === "failed" ? "error" : "info",
        message:
          job.status === "failed"
            ? `${label} failed${job.error ? `: ${job.error}` : ""}`
            : `${label} completed`,
      });
    }
  }

  return entries.sort((a, b) => a.timestamp - b.timestamp);
}

export function JobLogsTab({ jobs, selectedJobId }: JobLogsTabProps) {
  const [scope, setScope] = useState<LogScope>("all");

  const logEntries = useMemo(() => {
    const allEntries = toEntries(jobs);
    if (scope === "all") return allEntries;
    return allEntries.filter((entry) => entry.jobId === selectedJobId);
  }, [jobs, scope, selectedJobId]);

  return (
    <div className="h-full flex flex-col">
      <div className="shrink-0 flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setScope("all")}
            className={`text-[10px] px-2 py-1 rounded border ${scope === "all" ? "bg-accent border-input text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            All Tasks
          </button>
          <button
            type="button"
            onClick={() => setScope("selected")}
            className={`text-[10px] px-2 py-1 rounded border ${scope === "selected" ? "bg-accent border-input text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            Selected Task
          </button>
        </div>
        <span className="text-[10px] text-muted-foreground mono">
          {logEntries.length} entries
        </span>
      </div>

      {logEntries.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground">
          No lifecycle logs yet. Structured task logs will appear here in a future update.
        </div>
      ) : (
        <ScrollArea className="h-full">
          <div className="px-3 py-2 space-y-1">
            {logEntries.map((entry) => (
              <div
                key={entry.id}
                className="grid grid-cols-[56px_150px_1fr] gap-3 text-[11px] border-b border-border/50 py-1.5"
              >
                <span className={entry.level === "error" ? "text-red-400 mono" : "text-blue-400 mono"}>
                  {entry.level.toUpperCase()}
                </span>
                <span className="mono text-muted-foreground">
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
                <span className="mono text-foreground/90 break-all">{entry.message}</span>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
