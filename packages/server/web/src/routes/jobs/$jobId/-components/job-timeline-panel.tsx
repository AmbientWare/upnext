import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Panel } from "@/components/shared";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn, formatDuration } from "@/lib/utils";
import type { TreeJob } from "./timeline-model";
import { buildTimelineTicks, getBarPosition, getTimelineDomainAt } from "./timeline-model";

interface JobTimelinePanelProps {
  jobs: TreeJob[];
  selectedJobId: string;
  onSelectJob: (jobId: string) => void;
}

const statusBarClass: Record<string, string> = {
  active: "bg-blue-500/80",
  complete: "bg-emerald-500/80",
  failed: "bg-red-500/80",
  retrying: "bg-amber-500/80",
};

export function JobTimelinePanel({
  jobs,
  selectedJobId,
  onSelectJob,
}: JobTimelinePanelProps) {
  const hasActiveJobs = jobs.some((job) => job.status === "active" || job.status === "retrying");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const rowsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hasActiveJobs) return;

    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 250);

    return () => window.clearInterval(timer);
  }, [hasActiveJobs]);

  const domain = useMemo(
    () => getTimelineDomainAt(jobs, nowMs, { live: hasActiveJobs }),
    [jobs, nowMs, hasActiveJobs]
  );
  const ticks = useMemo(() => buildTimelineTicks(domain, 6), [domain]);
  const nowAtPct = Math.max(0, Math.min(100, ((nowMs - domain.min) / domain.span) * 100));

  useEffect(() => {
    const container = rowsRef.current;
    if (!container) return;

    const selected = container.querySelector<HTMLElement>(`[data-job-id="${selectedJobId}"]`);
    selected?.scrollIntoView({ block: "nearest" });
  }, [selectedJobId]);

  return (
    <Panel
      title="Execution Timeline"
      className="h-[360px] flex flex-col overflow-hidden"
      contentClassName="flex-1 overflow-hidden p-0"
    >
      <div className="hidden md:grid grid-cols-[minmax(180px,34%)_1fr] gap-2 px-3 py-2 border-b border-border">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Task</div>
        <div className="relative h-5">
          {ticks.map((tick) => (
            <span
              key={tick.ms}
              className="absolute top-0 -translate-x-1/2 mono text-[10px] text-muted-foreground/90 whitespace-nowrap"
              style={{ left: `${tick.at * 100}%` }}
            >
              {tick.label}
            </span>
          ))}
          {hasActiveJobs && (
            <span
              className="absolute -top-0.5 -translate-x-1/2 mono text-[10px] text-blue-300"
              style={{ left: `${nowAtPct}%` }}
            >
              now
            </span>
          )}
        </div>
      </div>

      <div className="md:hidden px-3 py-2 border-b border-border flex items-center justify-between text-[10px] text-muted-foreground mono">
        <span>{new Date(domain.min).toLocaleTimeString()}</span>
        <span>{new Date(domain.max).toLocaleTimeString()}</span>
      </div>

      <ScrollArea className="h-full">
        <div ref={rowsRef} className="min-w-0">
          {jobs.map((job) => {
            const bar = getBarPosition(job, domain, nowMs);
            const selected = selectedJobId === job.id;
            return (
              <button
                key={job.id}
                data-job-id={job.id}
                type="button"
                onClick={() => onSelectJob(job.id)}
                className={cn(
                  "w-full grid grid-cols-1 md:grid-cols-[minmax(180px,34%)_1fr] items-center gap-2 px-3 py-1.5 border-b border-border/60 text-left transition-colors",
                  selected ? "bg-accent/80" : "hover:bg-accent/40",
                )}
              >
                <div
                  className="min-w-0 flex items-center gap-1.5"
                  style={{ paddingLeft: `${job.depth * 14}px` }}
                >
                  {job.depth > 0 ? (
                    <ChevronRight className="w-3 h-3 text-muted-foreground" />
                  ) : (
                    <span className="w-3" />
                  )}
                  <span className="mono text-[11px] truncate">{job.function_name || job.function}</span>
                  <span className="text-[10px] text-muted-foreground truncate">
                    #{job.id.slice(0, 8)}
                  </span>
                </div>

                <div className="relative h-7 rounded border border-input bg-muted/30 overflow-hidden">
                  {ticks.map((tick) => (
                    <div
                      key={`${job.id}-${tick.ms}`}
                      className="absolute inset-y-0 w-px bg-border/40"
                      style={{ left: `${tick.at * 100}%` }}
                    />
                  ))}
                  {hasActiveJobs && (
                    <div
                      className="absolute inset-y-0 w-px bg-blue-300/70"
                      style={{ left: `${nowAtPct}%` }}
                    />
                  )}
                  <div
                    className={cn(
                      "absolute top-1/2 -translate-y-1/2 h-3 rounded transition-[left,width] duration-200 ease-linear",
                      statusBarClass[job.status] ?? "bg-primary/70",
                    )}
                    style={{ left: `${bar.left}%`, width: `${bar.width}%` }}
                  />
                  <div className="absolute inset-y-0 right-2 flex items-center text-[10px] text-muted-foreground mono">
                    {job.duration_ms ? formatDuration(job.duration_ms) : ""}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </Panel>
  );
}
