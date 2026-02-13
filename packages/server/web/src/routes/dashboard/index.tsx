import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  getDashboardStats,
  getWorkers,
  queryKeys,
} from "@/lib/upnext-api";
import {
  SystemOverviewPanel,
  type OverviewWindow,
} from "./-components/system-overview-panel";
import { QueueStatsPanel } from "./-components/queue-stats-panel";
import { QueueStatsSkeleton, SystemOverviewSkeleton } from "./-components/skeletons";
import { CombinedTrendsPanel } from "./-components/combined-trends-panel";
import { RunbookPanels } from "./-components/runbook-panels";

export const Route = createFileRoute("/dashboard/")({
  component: DataMatrixDashboard,
});

const WORKERS_SAFETY_RESYNC_MS = 10 * 60 * 1000;
const OVERVIEW_WINDOW_MINUTES: Record<OverviewWindow, 1 | 5 | 15 | 60 | 1440> = {
  "1m": 1,
  "5m": 5,
  "15m": 15,
  "1h": 60,
  "24h": 1440,
};

function DataMatrixDashboard() {
  const navigate = useNavigate();
  const [overviewWindow, setOverviewWindow] = useState<OverviewWindow>("5m");
  const [failingMinRate, setFailingMinRate] = useState<number>(10);
  const dashboardParams = useMemo(
    () => ({
      window_minutes: OVERVIEW_WINDOW_MINUTES[overviewWindow],
      failing_min_rate: failingMinRate,
    }),
    [overviewWindow, failingMinRate]
  );

  const { data: dashboardStats, isPending: isDashboardPending } = useQuery({
    queryKey: queryKeys.dashboardStatsWithParams(dashboardParams),
    queryFn: () => getDashboardStats(dashboardParams),
    // Safety fallback when SSE is degraded; normal updates are event-driven.
    refetchInterval: 5_000,
  });

  const { data: workersData, isPending: isWorkersPending } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: WORKERS_SAFETY_RESYNC_MS,
  });

  const workers = workersData?.workers ?? [];

  const isOverviewPending = isDashboardPending || isWorkersPending;

  return (
    <div className="p-4 flex flex-col gap-3 h-full min-h-0 overflow-auto xl:overflow-hidden">
      <div className="grid grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)] items-stretch gap-3 shrink-0">
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
            window={overviewWindow}
            onWindowChange={setOverviewWindow}
            className="shrink-0"
          />
        )}
      </div>

      {/* Trends + Runbook */}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,2fr)_minmax(340px,1fr)] gap-3 flex-1 min-h-[380px]">
        <CombinedTrendsPanel className="h-full" />

        <RunbookPanels
          stats={dashboardStats}
          isPending={isDashboardPending}
          failingMinRate={failingMinRate}
          onFailingMinRateChange={setFailingMinRate}
          className="h-full"
          onFunctionClick={(name) => navigate({ to: "/functions/$name", params: { name } })}
          onJobClick={(jobId) => navigate({ to: "/jobs/$jobId", params: { jobId } })}
        />
      </div>
    </div>
  );
}
