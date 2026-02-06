import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { formatDuration } from "@/lib/utils";
import {
  getDashboardStats,
  getWorkers,
  getApis,
  queryKeys,
} from "@/lib/conduit-api";
import type { Worker, ApiInfo, DashboardStats } from "@/lib/types";
import { SystemHealthPanel } from "./-components/system-health-panel";
import { ActiveWorkersPanel } from "./-components/active-workers-panel";
import { ActiveApisPanel } from "./-components/active-apis-panel";
import { QuickStats } from "./-components/quick-stats";
import { TrendsPanel } from "./-components/trends-panel";
import { ApiTrendsPanel } from "./-components/api-trends-panel";

export const Route = createFileRoute("/dashboard/")({
  component: DataMatrixDashboard,
});

// Transform API Worker to component format
function transformWorker(worker: Worker) {
  return {
    id: worker.id,
    name: worker.id,
    functions: worker.functions,
    concurrency: worker.concurrency,
    activeJobs: worker.active_jobs,
    jobsProcessed: worker.jobs_processed,
    jobsFailed: worker.jobs_failed,
    lastHeartbeat: new Date(worker.last_heartbeat),
  };
}

// Transform API to component format
function transformApi(api: ApiInfo) {
  return {
    name: api.name,
    endpointCount: api.endpoint_count,
    requestsPerMin: api.requests_per_min,
    avgLatencyMs: api.avg_latency_ms,
    errorRate: api.error_rate,
  };
}

// Calculate health metrics from dashboard stats
function calculateHealthMetrics(stats: DashboardStats | undefined) {
  if (!stats) {
    return [
      { label: "API Latency", value: "\u2014", status: "good" as const },
      { label: "Queued", value: "\u2014", status: "good" as const },
      { label: "Workers", value: "\u2014", status: "good" as const },
      { label: "Error Rate", value: "\u2014", status: "good" as const },
    ];
  }

  const apiLatency = stats.apis.avg_latency_ms;
  const errorRate = stats.apis.error_rate;

  return [
    {
      label: "API Latency",
      value: `${Math.round(apiLatency)}ms`,
      status: apiLatency < 100 ? ("good" as const) : apiLatency < 500 ? ("warn" as const) : ("bad" as const),
    },
    {
      label: "Queued",
      value: `${stats.runs.queued_count}`,
      status: stats.runs.queued_count < 100 ? ("good" as const) : ("warn" as const),
    },
    {
      label: "Workers",
      value: `${stats.workers.total}`,
      status: stats.workers.total > 0 ? ("good" as const) : ("bad" as const),
    },
    {
      label: "Error Rate",
      value: `${errorRate.toFixed(1)}%`,
      status: errorRate < 1 ? ("good" as const) : errorRate < 5 ? ("warn" as const) : ("bad" as const),
    },
  ];
}

// Calculate quick stats from dashboard stats
function calculateQuickStats(stats: DashboardStats | undefined) {
  if (!stats) {
    return [
      { label: "Throughput", value: "\u2014", color: "text-[#e0e0e0]" },
      { label: "P95 Latency", value: "\u2014", color: "text-amber-400" },
      { label: "Active Jobs", value: "\u2014", color: "text-[#e0e0e0]" },
      { label: "Success Rate", value: "\u2014", color: "text-violet-400" },
    ];
  }

  const throughput = Math.round(stats.runs.total_24h / 1440); // Per minute

  return [
    {
      label: "Throughput",
      value: throughput >= 1000 ? `${(throughput / 1000).toFixed(1)}K/min` : `${throughput}/min`,
      color: "text-[#e0e0e0]",
    },
    {
      label: "P95 Latency",
      value: formatDuration(stats.apis.avg_latency_ms * 2), // Estimate P95
      color: "text-amber-400",
    },
    {
      label: "Active Jobs",
      value: String(stats.runs.active_count),
      color: "text-[#e0e0e0]",
    },
    {
      label: "Success Rate",
      value: `${stats.runs.success_rate.toFixed(1)}%`,
      color: stats.runs.success_rate >= 99 ? "text-emerald-400" : "text-violet-400",
    },
  ];
}

// Determine system status from stats
function getSystemStatus(stats: DashboardStats | undefined): "operational" | "degraded" | "down" {
  if (!stats) return "down";
  if (stats.workers.total === 0) return "down";
  if (stats.apis.error_rate >= 5) return "down";
  if (stats.apis.error_rate >= 1) return "degraded";
  return "operational";
}

function DataMatrixDashboard() {
  // Fetch dashboard stats
  const { data: dashboardStats } = useQuery({
    queryKey: queryKeys.dashboardStats,
    queryFn: getDashboardStats,
    refetchInterval: 10000, // Refresh every 10s
  });

  // Fetch workers
  const { data: workersData } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: 10000,
  });

  // Fetch APIs
  const { data: apisData } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: getApis,
    refetchInterval: 15000,
  });

  // Transform data for components
  const workers = workersData?.workers.map(transformWorker) ?? [];
  const apis = apisData?.apis?.map(transformApi) ?? [];
  const healthMetrics = calculateHealthMetrics(dashboardStats);
  const quickStats = calculateQuickStats(dashboardStats);
  const systemStatus = getSystemStatus(dashboardStats);

  return (
    <div className="p-4 flex flex-col gap-3 h-full overflow-hidden">
      {/* Top - Trends Charts */}
      <div className="flex gap-3 min-h-0 flex-1">
        <TrendsPanel className="flex-1" />
        <ApiTrendsPanel className="flex-1" />
      </div>

      {/* Bottom - Active Workers, APIs & Status Summary */}
      <div className="flex gap-3 h-52 shrink-0">
        <ActiveWorkersPanel workers={workers} />
        <ActiveApisPanel apis={apis} />
        <SystemHealthPanel status={systemStatus} metrics={healthMetrics} className="w-56 shrink-0" />
        <QuickStats stats={quickStats} className="w-48 shrink-0" />
      </div>
    </div>
  );
}
