import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  getDashboardStats,
  getWorkers,
  getApis,
  getJobs,
  queryKeys,
} from "@/lib/conduit-api";
import { JobsTable } from "@/components/shared";
import { Panel } from "@/components/shared";
import { SystemOverviewPanel } from "./-components/system-overview-panel";
import { TrendsPanel } from "./-components/trends-panel";
import { ApiTrendsPanel } from "./-components/api-trends-panel";

export const Route = createFileRoute("/dashboard/")({
  component: DataMatrixDashboard,
});

function DataMatrixDashboard() {
  const { data: dashboardStats } = useQuery({
    queryKey: queryKeys.dashboardStats,
    queryFn: getDashboardStats,
    refetchInterval: 10000,
  });

  const { data: workersData } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: 10000,
  });

  const { data: apisData } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: getApis,
    refetchInterval: 15000,
  });

  const { data: jobsData } = useQuery({
    queryKey: queryKeys.jobs({ limit: 50 }),
    queryFn: () => getJobs({ limit: 50 }),
    refetchInterval: 5000,
  });

  const workers = workersData?.workers ?? [];
  const apis = apisData?.apis ?? [];
  const jobs = jobsData?.jobs ?? [];

  return (
    <div className="p-4 flex flex-col gap-3 h-full overflow-auto">
      {/* System Overview */}
      <SystemOverviewPanel
        stats={dashboardStats}
        workers={workers}
        apis={apis}
        className="shrink-0"
      />

      {/* Trends Charts */}
      <div className="flex gap-3 h-56 shrink-0">
        <TrendsPanel className="flex-1" />
        <ApiTrendsPanel className="flex-1" />
      </div>

      {/* Recent Jobs */}
      <Panel title="Recent Jobs" className="flex-1 min-h-64 flex flex-col overflow-hidden" contentClassName="flex-1 overflow-hidden">
        {jobs.length === 0 ? (
          <div className="flex items-center justify-center h-full text-[#555] text-xs">
            No jobs found
          </div>
        ) : (
          <JobsTable jobs={jobs} />
        )}
      </Panel>
    </div>
  );
}
