import { useMemo, useState } from "react";
import { cn, formatDuration, formatTimeAgo } from "@/lib/utils";
import { StatusBadge } from "./status-badge";
import { ProgressBar } from "./progress-bar";
import { Panel } from "./panel";
import type { Job } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const statusFilters = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "complete", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "retrying", label: "Retrying" },
] as const;

interface JobsTablePanelProps {
  jobs: Job[];
  onJobClick?: (job: Job) => void;
  /** Hide the function column (useful when viewing a single function). */
  hideFunction?: boolean;
  /** Show status filter tabs in the panel header. */
  showFilters?: boolean;
  className?: string;
}

export function JobsTablePanel({
  jobs,
  onJobClick,
  hideFunction,
  showFilters,
  className,
}: JobsTablePanelProps) {
  const [filter, setFilter] = useState("all");

  const filteredJobs = useMemo(
    () => filter === "all" ? jobs : jobs.filter((j) => j.status === filter),
    [jobs, filter],
  );

  return (
    <Panel
      title="Recent Jobs"
      className={className ?? "flex-1 min-h-64 flex flex-col overflow-hidden"}
      contentClassName="flex-1 overflow-hidden"
      titleRight={
        showFilters ? (
          <div className="flex items-center gap-1">
            {statusFilters.map((sf) => (
              <button
                key={sf.value}
                onClick={() => setFilter(sf.value)}
                className={cn(
                  "px-2 py-0.5 text-[10px] rounded transition-colors",
                  filter === sf.value
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {sf.label}
              </button>
            ))}
          </div>
        ) : undefined
      }
    >
      {filteredJobs.length === 0 ? (
        <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
          No jobs found
        </div>
      ) : (
        <div className="flex flex-col h-full overflow-hidden">
          <div className="flex-1 overflow-auto">
            <Table>
              <TableHeader className="sticky top-0 z-10 bg-card">
                <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8">ID</TableHead>
                  {!hideFunction && (
                    <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Function</TableHead>
                  )}
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Status</TableHead>
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Duration</TableHead>
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Worker</TableHead>
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Age</TableHead>
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Progress</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredJobs.map((job) => (
                  <TableRow
                    key={job.id}
                    onClick={() => onJobClick?.(job)}
                    className="border-border hover:bg-accent cursor-pointer"
                  >
                    <TableCell className="mono text-[11px] text-muted-foreground py-1.5">{job.id.slice(0, 12)}</TableCell>
                    {!hideFunction && (
                      <TableCell className="text-[11px] py-1.5">{job.function}</TableCell>
                    )}
                    <TableCell className="py-1.5">
                      <StatusBadge status={job.status} />
                    </TableCell>
                    <TableCell className="mono text-[11px] text-muted-foreground py-1.5">
                      {job.duration_ms ? formatDuration(job.duration_ms) : "\u2014"}
                    </TableCell>
                    <TableCell className="mono text-[11px] text-muted-foreground py-1.5">{job.worker_id || "\u2014"}</TableCell>
                    <TableCell className="text-[11px] text-muted-foreground py-1.5">
                      {job.scheduled_at ? formatTimeAgo(new Date(job.scheduled_at)) : "\u2014"}
                    </TableCell>
                    <TableCell className="py-1.5">
                      {job.status === "active" && job.progress !== undefined && job.progress > 0 ? (
                        <ProgressBar value={job.progress * 100} showLabel size="sm" />
                      ) : (
                        <span className="text-muted-foreground/40">{"\u2014"}</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </Panel>
  );
}
