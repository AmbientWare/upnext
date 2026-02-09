import { useMemo, useState } from "react";

import type { ApiRequestEvent, Job } from "@/lib/types";
import { Panel, JobsTable, ApiRequestsTable } from "@/components/shared";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

interface LiveActivityPanelProps {
  jobs: Job[];
  apiRequestEvents: ApiRequestEvent[];
  isJobsLoading?: boolean;
  isApiLoading?: boolean;
  onJobClick?: (job: Job) => void;
  onApiClick?: (apiName: string) => void;
  className?: string;
}

const statusFilters = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "complete", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "retrying", label: "Retrying" },
] as const;

export function LiveActivityPanel({
  jobs,
  apiRequestEvents,
  isJobsLoading = false,
  isApiLoading = false,
  onJobClick,
  onApiClick,
  className,
}: LiveActivityPanelProps) {
  const [activeTab, setActiveTab] = useState("jobs");
  const [statusFilter, setStatusFilter] = useState("all");

  const filteredJobs = useMemo(
    () =>
      statusFilter === "all"
        ? jobs
        : jobs.filter((job) => job.status === statusFilter),
    [jobs, statusFilter]
  );

  const statusFilterControls = (
    <div className="flex items-center gap-1">
      {statusFilters.map((status) => (
        <button
          key={status.value}
          type="button"
          onClick={() => setStatusFilter(status.value)}
          className={
            statusFilter === status.value
              ? "px-2 py-0.5 text-[10px] rounded bg-accent text-foreground"
              : "px-2 py-0.5 text-[10px] rounded text-muted-foreground hover:text-foreground"
          }
        >
          {status.label}
        </button>
      ))}
    </div>
  );

  return (
    <Panel
      title="Live Activity"
      className={className ?? "flex-1 min-h-72 flex flex-col overflow-hidden"}
      contentClassName="flex-1 overflow-hidden p-0"
      titleRight={activeTab === "jobs" ? statusFilterControls : undefined}
    >
      <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full">
        <div className="px-3 pt-2 border-b border-border">
          <TabsList variant="line" className="h-8">
            <TabsTrigger value="jobs" className="text-xs">Jobs ({jobs.length})</TabsTrigger>
            <TabsTrigger value="api-requests" className="text-xs">API Events ({apiRequestEvents.length})</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="jobs" className="h-full m-0">
          <JobsTable
            jobs={filteredJobs}
            isLoading={isJobsLoading}
            onJobClick={onJobClick}
            className="h-full"
            emptyDescription={
              statusFilter === "all"
                ? "Jobs will show up here as workers report progress."
                : `No ${statusFilter} jobs in this view right now.`
            }
          />
        </TabsContent>

        <TabsContent value="api-requests" className="h-full m-0">
          <ApiRequestsTable
            events={apiRequestEvents}
            isLoading={isApiLoading}
            onApiClick={onApiClick}
            className="h-full"
          />
        </TabsContent>
      </Tabs>
    </Panel>
  );
}
