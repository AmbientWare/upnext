import { createFileRoute } from "@tanstack/react-router";
import { useMemo } from "react";
import { formatDuration } from "@/lib/utils";
import {
  generateMockWorkers,
  generateMockStats,
  generateMockApis,
} from "@/lib/mock-data";
import { SystemHealthPanel } from "./-components/system-health-panel";
import { ActiveWorkersPanel } from "./-components/active-workers-panel";
import { ActiveApisPanel } from "./-components/active-apis-panel";
import { QuickStats } from "./-components/quick-stats";
import { TrendsPanel } from "./-components/trends-panel";
import { ApiTrendsPanel } from "./-components/api-trends-panel";

export const Route = createFileRoute("/dashboard/")({
  component: DataMatrixDashboard,
});

function DataMatrixDashboard() {
  const stats = useMemo(() => generateMockStats(), []);
  const workers = useMemo(() => generateMockWorkers(), []);
  const apis = useMemo(() => generateMockApis(), []);

  const healthMetrics = [
    { label: "API Latency", value: "12ms", status: "good" as const },
    { label: "Queue Latency", value: "45ms", status: "good" as const },
    { label: "Worker Pool", value: "75%", status: "warn" as const },
    { label: "Error Rate", value: "0.3%", status: "good" as const },
  ];

  const quickStats = [
    { label: "Throughput", value: "1.2K/min", color: "text-[#e0e0e0]" },
    { label: "P95 Latency", value: formatDuration(stats.p95Duration), color: "text-amber-400" },
    { label: "Queue Wait", value: "2.3s", color: "text-[#e0e0e0]" },
    { label: "Retry Rate", value: "1.2%", color: "text-violet-400" },
  ];

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
        <SystemHealthPanel status="operational" metrics={healthMetrics} className="w-56 shrink-0" />
        <QuickStats stats={quickStats} className="w-48 shrink-0" />
      </div>
    </div>
  );
}
