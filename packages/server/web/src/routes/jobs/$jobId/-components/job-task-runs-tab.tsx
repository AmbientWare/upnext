import { ChevronRight } from "lucide-react";
import { StatusBadge } from "@/components/shared/status-badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn, formatDuration } from "@/lib/utils";
import type { TreeJob } from "./timeline-model";

interface JobTaskRunsTabProps {
  jobs: TreeJob[];
  selectedJobId: string;
  onSelectJob: (jobId: string) => void;
}

export function JobTaskRunsTab({
  jobs,
  selectedJobId,
  onSelectJob,
}: JobTaskRunsTabProps) {
  return (
    <div className="h-full overflow-hidden">
      <ScrollArea className="h-full">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
              <TableHead className="h-8 text-[10px] font-medium text-muted-foreground">Task</TableHead>
              <TableHead className="h-8 text-[10px] font-medium text-muted-foreground">Status</TableHead>
              <TableHead className="h-8 text-[10px] font-medium text-muted-foreground">Duration</TableHead>
              <TableHead className="h-8 text-[10px] font-medium text-muted-foreground">Worker</TableHead>
              <TableHead className="h-8 text-[10px] font-medium text-muted-foreground">Attempts</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => (
              <TableRow
                key={job.id}
                onClick={() => onSelectJob(job.id)}
                className={cn(
                  "border-border cursor-pointer hover:bg-accent/60",
                  selectedJobId === job.id && "bg-accent/80",
                )}
              >
                <TableCell className="py-1.5">
                  <div
                    className="flex items-center gap-1.5 min-w-0"
                    style={{ paddingLeft: `${job.depth * 14}px` }}
                  >
                    {job.depth > 0 ? (
                      <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
                    ) : (
                      <span className="w-3 shrink-0" />
                    )}
                    <span className="mono text-[11px] truncate">{job.function_name || job.function}</span>
                    <span className="mono text-[10px] text-muted-foreground shrink-0">
                      {job.id.slice(0, 8)}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="py-1.5">
                  <StatusBadge status={job.status} />
                </TableCell>
                <TableCell className="py-1.5 mono text-[11px] text-muted-foreground">
                  {job.duration_ms ? formatDuration(job.duration_ms) : "—"}
                </TableCell>
                <TableCell className="py-1.5 mono text-[11px] text-muted-foreground">
                  {job.worker_id ?? "—"}
                </TableCell>
                <TableCell className="py-1.5 mono text-[11px] text-muted-foreground">
                  {job.attempts}/{job.max_retries + 1}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </ScrollArea>
    </div>
  );
}
