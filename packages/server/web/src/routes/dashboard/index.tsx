import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  getDashboardStats,
  getWorkers,
  getApis,
  queryKeys,
} from "@/lib/upnext-api";
import { SystemOverviewPanel } from "./-components/system-overview-panel";
import { QueueStatsPanel } from "./-components/queue-stats-panel";
import { QueueStatsSkeleton, SystemOverviewSkeleton } from "./-components/skeletons";
import { TrendsPanel } from "./-components/trends-panel";
import { ApiTrendsPanel } from "./-components/api-trends-panel";
import { LiveActivityPanel } from "./-components/live-activity-panel";

export const Route = createFileRoute("/dashboard/")({
  component: DataMatrixDashboard,
});

const WORKERS_SAFETY_RESYNC_MS = 10 * 60 * 1000;
const APIS_DASHBOARD_RESYNC_MS = 30 * 1000;

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
    refetchInterval: APIS_DASHBOARD_RESYNC_MS,
  });

  const workers = workersData?.workers ?? [];
  const apis = apisData?.apis ?? [];

  const isOverviewPending = isDashboardPending || isWorkersPending || isApisPending;

  return (
    <div className="p-4 flex flex-col gap-3 h-full min-h-0 overflow-hidden">
      <div className="grid grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)] items-stretch gap-3 shrink-0">
        {/* Queue Stats */}
        {isOverviewPending ? (
          <QueueStatsSkeleton />
        ) : (
          <QueueStatsPanel
            stats={dashboardStats}
            className="h-full"
          />
        )}

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
      </div>

      {/* Trends Charts */}
      <div className="flex gap-3 h-56 shrink-0">
        <TrendsPanel className="flex-1" />
        <ApiTrendsPanel className="flex-1" />
      </div>

      <LiveActivityPanel
        onJobClick={(job) => navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })}
        onApiClick={(apiName) => navigate({ to: "/apis/$name", params: { name: apiName } })}
      />
    </div>
  );
}
