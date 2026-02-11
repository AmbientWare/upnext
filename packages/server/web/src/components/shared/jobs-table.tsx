import type { ReactNode } from "react";
import { Inbox } from "lucide-react";
import { cn, formatDateTime, formatDuration, formatTimeAgo } from "@/lib/utils";
import { StatusBadge } from "./status-badge";
import { ProgressBar } from "./progress-bar";
import { Skeleton } from "@/components/ui/skeleton";
import type { Job } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface JobsTableProps {
  jobs: Job[];
  onJobClick?: (job: Job) => void;
  renderActions?: (job: Job) => ReactNode;
  hideFunction?: boolean;
  isLoading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  className?: string;
}

function JobsTableSkeleton({
  hideFunction,
  showActions = false,
}: {
  hideFunction?: boolean;
  showActions?: boolean;
}) {
  return (
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
          <TableHead className="hidden lg:table-cell text-[10px] text-muted-foreground font-medium h-8">Started</TableHead>
          <TableHead className="hidden lg:table-cell text-[10px] text-muted-foreground font-medium h-8">Finished</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Age</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Progress</TableHead>
          {showActions && (
            <TableHead className="text-[10px] text-muted-foreground font-medium h-8 text-right">Actions</TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 6 }).map((_, index) => (
          <TableRow key={`job-skeleton-${index}`} className="border-border">
            <TableCell className="py-1.5">
              <Skeleton className="h-3 w-20" />
            </TableCell>
            {!hideFunction && (
              <TableCell className="py-1.5">
                <Skeleton className="h-3 w-24" />
              </TableCell>
            )}
            <TableCell className="py-1.5">
              <Skeleton className="h-4 w-14" />
            </TableCell>
            <TableCell className="py-1.5">
              <Skeleton className="h-3 w-16" />
            </TableCell>
            <TableCell className="py-1.5">
              <Skeleton className="h-3 w-24" />
            </TableCell>
            <TableCell className="hidden lg:table-cell py-1.5">
              <Skeleton className="h-3 w-28" />
            </TableCell>
            <TableCell className="hidden lg:table-cell py-1.5">
              <Skeleton className="h-3 w-28" />
            </TableCell>
            <TableCell className="py-1.5">
              <Skeleton className="h-3 w-12" />
            </TableCell>
            <TableCell className="py-1.5">
              <Skeleton className="h-2 w-20" />
            </TableCell>
            {showActions && (
              <TableCell className="py-1.5">
                <div className="ml-auto w-20">
                  <Skeleton className="h-6 w-20" />
                </div>
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function JobsTable({
  jobs,
  onJobClick,
  renderActions,
  hideFunction,
  isLoading = false,
  emptyTitle = "No jobs yet",
  emptyDescription = "Jobs will show up here as workers report progress.",
  className,
}: JobsTableProps) {
  return (
    <div className={cn("flex flex-col h-full overflow-hidden", className)}>
      {isLoading ? (
        <div className="flex-1 overflow-auto">
          <JobsTableSkeleton hideFunction={hideFunction} showActions={Boolean(renderActions)} />
        </div>
      ) : jobs.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
          <div className="rounded-full bg-muted/60 p-2">
            <Inbox className="h-4 w-4" />
          </div>
          <div className="text-sm font-medium">{emptyTitle}</div>
          <div className="text-xs text-muted-foreground/80">{emptyDescription}</div>
        </div>
      ) : (
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
                <TableHead className="hidden lg:table-cell text-[10px] text-muted-foreground font-medium h-8">Started</TableHead>
                <TableHead className="hidden lg:table-cell text-[10px] text-muted-foreground font-medium h-8">Finished</TableHead>
                <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Age</TableHead>
                <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Progress</TableHead>
                {renderActions && (
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8 text-right">Actions</TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((job) => {
                const ageSource =
                  job.created_at ??
                  job.scheduled_at ??
                  job.started_at ??
                  job.completed_at;

                return (
                  <TableRow
                    key={job.id}
                    onClick={onJobClick ? () => onJobClick(job) : undefined}
                    className={cn(
                      "border-border hover:bg-accent",
                      onJobClick && "cursor-pointer"
                    )}
                  >
                    <TableCell className="mono text-[11px] text-muted-foreground py-1.5">{job.id.slice(0, 12)}</TableCell>
                    {!hideFunction && (
                      <TableCell className="text-[11px] py-1.5">{job.function_name || job.function}</TableCell>
                    )}
                    <TableCell className="py-1.5">
                      <StatusBadge status={job.status} />
                    </TableCell>
                    <TableCell className="mono text-[11px] text-muted-foreground py-1.5">
                      {job.duration_ms ? formatDuration(job.duration_ms) : "\u2014"}
                    </TableCell>
                    <TableCell className="mono text-[11px] text-muted-foreground py-1.5">{job.worker_id || "\u2014"}</TableCell>
                    <TableCell className="hidden lg:table-cell mono text-[11px] text-muted-foreground py-1.5">
                      {job.started_at ? formatDateTime(new Date(job.started_at)) : "\u2014"}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell mono text-[11px] text-muted-foreground py-1.5">
                      {job.completed_at ? formatDateTime(new Date(job.completed_at)) : "\u2014"}
                    </TableCell>
                    <TableCell className="text-[11px] text-muted-foreground py-1.5">
                      {ageSource ? formatTimeAgo(new Date(ageSource)) : "\u2014"}
                    </TableCell>
                    <TableCell className="py-1.5">
                      {job.status === "active" && job.progress !== undefined && job.progress > 0 ? (
                        <ProgressBar value={job.progress * 100} showLabel size="sm" />
                      ) : (
                        <span className="text-muted-foreground/40">{"\u2014"}</span>
                      )}
                    </TableCell>
                    {renderActions && (
                      <TableCell
                        className="py-1.5 text-right"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {renderActions(job)}
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
