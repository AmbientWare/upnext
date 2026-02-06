import { formatDuration, formatTimeAgo } from "@/lib/utils";
import { StatusBadge } from "./status-badge";
import { ProgressBar } from "./progress-bar";
import type { Job } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface JobsTableProps {
  jobs: Job[];
  onJobClick?: (job: Job) => void;
}

export function JobsTable({ jobs, onJobClick }: JobsTableProps) {
  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">ID</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Function</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Status</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Duration</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Worker</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Age</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Progress</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow
            key={job.id}
            onClick={() => onJobClick?.(job)}
            className="border-border hover:bg-accent cursor-pointer"
          >
            <TableCell className="mono text-[11px] text-muted-foreground py-1.5">{job.id.slice(0, 12)}</TableCell>
            <TableCell className="text-[11px] py-1.5">{job.function}</TableCell>
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
  );
}
