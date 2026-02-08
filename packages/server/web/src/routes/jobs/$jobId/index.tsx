import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getJobTimeline, queryKeys } from "@/lib/conduit-api";
import { Panel } from "@/components/shared";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { JobRunHeader } from "./-components/job-run-header";
import { JobTimelinePanel } from "./-components/job-timeline-panel";
import { JobTaskRunsTab } from "./-components/job-task-runs-tab";
import { JobLogsTab } from "./-components/job-logs-tab";
import { JobArtifactsTab } from "./-components/job-artifacts-tab";
import { JobDetailsPanel } from "./-components/job-details-panel";
import { JobDetailSkeleton } from "./-components/skeletons";
import { buildJobTree } from "./-components/timeline-model";

export const Route = createFileRoute("/jobs/$jobId/")({
  component: JobDetailPage,
});

function JobDetailPage() {
  const { jobId } = Route.useParams();
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState(jobId);
  const [activeTab, setActiveTab] = useState("task-runs");

  useEffect(() => {
    setSelectedJobId(jobId);
  }, [jobId]);

  const { data, isPending } = useQuery({
    queryKey: queryKeys.jobTimeline(jobId),
    queryFn: () => getJobTimeline(jobId),
    refetchInterval: 2500,
  });

  const timelineJobs = useMemo(() => data?.jobs ?? [], [data]);
  const treeJobs = useMemo(() => buildJobTree(timelineJobs, jobId), [timelineJobs, jobId]);
  const rootJob = treeJobs.find((job) => job.id === jobId);
  const selectedJob = treeJobs.find((job) => job.id === selectedJobId)
    ?? rootJob;
  const effectiveSelectedJobId = selectedJob?.id ?? jobId;
  const hasActiveJobs = treeJobs.some((job) => job.status === "active" || job.status === "retrying");
  const artifactRefreshMs = hasActiveJobs ? 3000 : 15000;

  if (isPending && !rootJob) {
    return <JobDetailSkeleton />;
  }

  if (!rootJob || !selectedJob) {
    return (
      <div className="p-4 h-full flex items-center justify-center text-sm text-muted-foreground">
        Job not found.
      </div>
    );
  }

  return (
    <div className="p-4 h-full flex flex-col gap-3 overflow-auto xl:overflow-hidden">
      <JobRunHeader job={rootJob} />

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(340px,380px)] gap-3 min-h-0 flex-1">
        <div className="min-h-0 flex flex-col gap-3">
          <JobTimelinePanel
            jobs={treeJobs}
            selectedJobId={effectiveSelectedJobId}
            onSelectJob={setSelectedJobId}
          />

          <Panel
            title="Task Activity"
            className="flex-1 min-h-[280px] flex flex-col overflow-hidden"
            contentClassName="flex-1 p-0 overflow-hidden"
          >
            <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full">
              <div className="px-3 pt-2 border-b border-border flex items-center justify-between gap-2">
                <TabsList variant="line" className="h-8">
                  <TabsTrigger value="task-runs" className="text-xs">Task Runs</TabsTrigger>
                  <TabsTrigger value="logs" className="text-xs">Logs</TabsTrigger>
                  <TabsTrigger value="artifacts" className="text-xs">Artifacts</TabsTrigger>
                </TabsList>
                {activeTab === "artifacts" && (
                  <button
                    type="button"
                    onClick={() => {
                      void queryClient.refetchQueries({
                        queryKey: queryKeys.jobArtifacts(effectiveSelectedJobId),
                        exact: true,
                      });
                    }}
                    className="h-7 w-7 inline-flex items-center justify-center rounded border border-input text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                    aria-label="Refresh artifacts"
                    title="Refresh artifacts"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <TabsContent value="task-runs" className="h-full m-0">
                <JobTaskRunsTab
                  jobs={treeJobs}
                  selectedJobId={effectiveSelectedJobId}
                  onSelectJob={setSelectedJobId}
                />
              </TabsContent>

              <TabsContent value="logs" className="h-full m-0">
                <JobLogsTab jobs={treeJobs} selectedJobId={effectiveSelectedJobId} />
              </TabsContent>

              <TabsContent value="artifacts" className="h-full m-0">
                <JobArtifactsTab
                  selectedJobId={effectiveSelectedJobId}
                  refreshMs={artifactRefreshMs}
                />
              </TabsContent>
            </Tabs>
          </Panel>
        </div>

        <div className="min-h-0">
          <JobDetailsPanel job={selectedJob} />
        </div>
      </div>
    </div>
  );
}
