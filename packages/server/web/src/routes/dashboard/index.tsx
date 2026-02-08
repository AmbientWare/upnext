import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  getDashboardStats,
  getWorkers,
  getApis,
  getJobs,
  queryKeys,
} from "@/lib/conduit-api";
import { JobsTablePanel } from "@/components/shared";
import { SystemOverviewPanel } from "./-components/system-overview-panel";
import { SystemOverviewSkeleton } from "./-components/skeletons";
import { TrendsPanel } from "./-components/trends-panel";
import { ApiTrendsPanel } from "./-components/api-trends-panel";

export const Route = createFileRoute("/dashboard/")({
  component: DataMatrixDashboard,
});

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
    refetchInterval: 30000,
  });

  const { data: apisData, isPending: isApisPending } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: getApis,
    refetchInterval: 45000,
  });

  const { data: jobsData, isPending: isJobsPending } = useQuery({
    queryKey: queryKeys.jobs({ limit: 50 }),
    queryFn: () => getJobs({ limit: 50 }),
    refetchInterval: 30000,
  });

  const workers = workersData?.workers ?? [];
  const apis = apisData?.apis ?? [];
  const jobs = jobsData?.jobs ?? [];

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

      {/* Recent Jobs */}
      <JobsTablePanel
        jobs={jobs}
        showFilters
        isLoading={isJobsPending}
        onJobClick={(job) => navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })}
      />
    </div>
  );
}
