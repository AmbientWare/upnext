import { useMemo, useState, type ReactNode } from "react";

import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Panel } from "./panel";
import { JobsTable } from "./jobs-table";

const statusFilters = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "queued", label: "Queued" },
  { value: "active", label: "Active" },
  { value: "complete", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "retrying", label: "Retrying" },
] as const;

interface JobsTablePanelProps {
  jobs: Job[];
  onJobClick?: (job: Job) => void;
  renderActions?: (job: Job) => ReactNode;
  hideFunction?: boolean;
  showFilters?: boolean;
  headerControls?: ReactNode;
  isLoading?: boolean;
  className?: string;
  title?: string;
}

export function JobsTablePanel({
  jobs,
  onJobClick,
  renderActions,
  hideFunction,
  showFilters,
  headerControls,
  isLoading = false,
  className,
  title = "Recent Jobs",
}: JobsTablePanelProps) {
  const [filter, setFilter] = useState("all");

  const filteredJobs = useMemo(
    () => (filter === "all" ? jobs : jobs.filter((job) => job.status === filter)),
    [jobs, filter]
  );

  const emptyDescription =
    filter === "all"
      ? "Jobs will show up here as workers report progress."
      : `No ${filter} jobs in this view right now.`;

  return (
    <Panel
      title={title}
      className={className ?? "flex-1 min-h-64 flex flex-col overflow-hidden"}
      contentClassName="flex-1 overflow-hidden"
      titleRight={
        showFilters || headerControls ? (
          <div className="flex items-center gap-2">
            {showFilters ? (
              <div className="flex items-center gap-1">
                {statusFilters.map((statusFilter) => (
                  <button
                    key={statusFilter.value}
                    type="button"
                    onClick={() => setFilter(statusFilter.value)}
                    className={cn(
                      "px-2 py-0.5 text-[10px] rounded transition-colors",
                      filter === statusFilter.value
                        ? "bg-accent text-foreground"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {statusFilter.label}
                  </button>
                ))}
              </div>
            ) : null}
            {headerControls}
          </div>
        ) : undefined
      }
    >
      <JobsTable
        jobs={filteredJobs}
        onJobClick={onJobClick}
        renderActions={renderActions}
        hideFunction={hideFunction}
        isLoading={isLoading}
        emptyDescription={emptyDescription}
      />
    </Panel>
  );
}
