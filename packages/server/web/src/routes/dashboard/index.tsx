import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  getDashboardStats,
  getWorkers,
  getApis,
  getApiRequestEvents,
  getJobs,
  queryKeys,
} from "@/lib/upnext-api";
import { SystemOverviewPanel } from "./-components/system-overview-panel";
import { SystemOverviewSkeleton } from "./-components/skeletons";
import { TrendsPanel } from "./-components/trends-panel";
import { ApiTrendsPanel } from "./-components/api-trends-panel";
import { LiveActivityPanel } from "./-components/live-activity-panel";

export const Route = createFileRoute("/dashboard/")({
  component: DataMatrixDashboard,
});

const SAFETY_RESYNC_MS = 10 * 60 * 1000;
const WORKERS_SAFETY_RESYNC_MS = 60 * 1000;
const LIVE_ACTIVITY_LIMIT = 50;

function toTimestamp(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function DataMatrixDashboard() {
  const navigate = useNavigate();

  const { data: dashboardStats, isPending: isDashboardPending } = useQuery({
    queryKey: queryKeys.dashboardStats,
    queryFn: getDashboardStats,
    refetchInterval: 30000,
  });

  const { data: workersData, isPending: isWorkersPending } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: WORKERS_SAFETY_RESYNC_MS,
  });

  const { data: apisData, isPending: isApisPending } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: getApis,
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const { data: jobsData, isPending: isJobsPending } = useQuery({
    queryKey: queryKeys.jobs({ limit: 50 }),
    queryFn: () => getJobs({ limit: 50 }),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const { data: apiRequestEventsData, isPending: isApiEventsPending } = useQuery({
    queryKey: queryKeys.apiRequestEvents({ limit: 200 }),
    queryFn: () => getApiRequestEvents({ limit: 200 }),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const workers = workersData?.workers ?? [];
  const apis = apisData?.apis ?? [];
  const jobs = useMemo(() => {
    return [...(jobsData?.jobs ?? [])]
      .sort((a, b) => {
        const aTime = Math.max(toTimestamp(a.created_at), toTimestamp(a.scheduled_at), toTimestamp(a.started_at), toTimestamp(a.completed_at));
        const bTime = Math.max(toTimestamp(b.created_at), toTimestamp(b.scheduled_at), toTimestamp(b.started_at), toTimestamp(b.completed_at));
        return bTime - aTime;
      })
      .slice(0, LIVE_ACTIVITY_LIMIT);
  }, [jobsData?.jobs]);

  const apiRequestEvents = useMemo(() => {
    return [...(apiRequestEventsData?.events ?? [])]
      .sort((a, b) => toTimestamp(b.at) - toTimestamp(a.at))
      .slice(0, LIVE_ACTIVITY_LIMIT);
  }, [apiRequestEventsData?.events]);

  const isOverviewPending = isDashboardPending || isWorkersPending || isApisPending;

  return (
    <div className="p-4 flex flex-col gap-3 h-full overflow-auto">
      {/* System Overview */}
      {isOverviewPending ? (
        <SystemOverviewSkeleton />
      ) : (
        <SystemOverviewPanel
          stats={dashboardStats}
          workers={workers}
          apis={apis}
          className="shrink-0"
        />
      )}

      {/* Trends Charts */}
      <div className="flex gap-3 h-56 shrink-0">
        <TrendsPanel className="flex-1" />
        <ApiTrendsPanel className="flex-1" />
      </div>

      <LiveActivityPanel
        jobs={jobs}
        apiRequestEvents={apiRequestEvents}
        isJobsLoading={isJobsPending}
        isApiLoading={isApiEventsPending}
        onJobClick={(job) => navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })}
        onApiClick={(apiName) => navigate({ to: "/apis/$name", params: { name: apiName } })}
      />
    </div>
  );
}
