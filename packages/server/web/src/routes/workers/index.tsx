import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { cn, formatTimeAgo, formatNumber } from "@/lib/utils";
import { generateMockWorkers, type Worker } from "@/lib/mock-data";
import { Search, X, ChevronDown } from "lucide-react";
import { ProgressBar } from "@/components/shared";

export const Route = createFileRoute("/workers/")({
  component: WorkersPage,
});

type WorkerStatus = "healthy" | "unhealthy" | "offline";

const statusOptions: { value: WorkerStatus | ""; label: string }[] = [
  { value: "", label: "All Statuses" },
  { value: "healthy", label: "Healthy" },
  { value: "unhealthy", label: "Unhealthy" },
  { value: "offline", label: "Offline" },
];

const statusStyles: Record<WorkerStatus, { dot: string; text: string }> = {
  healthy: { dot: "bg-emerald-500", text: "text-emerald-400" },
  unhealthy: { dot: "bg-amber-500", text: "text-amber-400" },
  offline: { dot: "bg-red-500", text: "text-red-400" },
};

function WorkersPage() {
  const allWorkers = useMemo(() => generateMockWorkers(), []);
  const [search, setSearch] = useState("");
  const [selectedStatus, setSelectedStatus] = useState<WorkerStatus | "">("");

  const filteredWorkers = useMemo(() => {
    let workers = allWorkers;

    if (search) {
      const searchLower = search.toLowerCase();
      workers = workers.filter(
        (w) =>
          w.name.toLowerCase().includes(searchLower) ||
          w.id.toLowerCase().includes(searchLower) ||
          w.functions.some((fn) => fn.toLowerCase().includes(searchLower))
      );
    }

    if (selectedStatus) {
      workers = workers.filter((w) => w.status === selectedStatus);
    }

    return workers;
  }, [allWorkers, search, selectedStatus]);

  const clearFilters = () => {
    setSearch("");
    setSelectedStatus("");
  };

  const hasFilters = search || selectedStatus;

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      {/* Filters Bar */}
      <div className="flex items-center gap-4 shrink-0">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555]" />
          <input
            type="text"
            placeholder="Search workers..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64 bg-[#1a1a1a] border border-[#2a2a2a] rounded-md pl-9 pr-3 py-2 text-sm text-[#e0e0e0] placeholder-[#555] focus:outline-none focus:border-[#3a3a3a]"
          />
        </div>

        {/* Status Filter */}
        <div className="relative">
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value as WorkerStatus | "")}
            className={cn(
              "appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded-md px-3 py-2 pr-8 text-sm focus:outline-none focus:border-[#3a3a3a]",
              selectedStatus ? "text-[#e0e0e0]" : "text-[#555]"
            )}
          >
            {statusOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />
        </div>

        {/* Clear Filters */}
        {hasFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1 px-2 py-1.5 text-xs text-[#666] hover:text-[#999] transition-colors"
          >
            <X className="w-3 h-3" />
            Clear
          </button>
        )}

        <div className="flex-1" />

        {/* Results count */}
        <span className="text-xs text-[#555] mono">
          {filteredWorkers.length} of {allWorkers.length} workers
        </span>
      </div>

      {/* Workers Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        <div className="h-full overflow-auto">
          <WorkersTable workers={filteredWorkers} />
        </div>
      </div>
    </div>
  );
}

const hostingStyles = {
  managed: "bg-sky-500/20 text-sky-400",
  "self-hosted": "bg-violet-500/20 text-violet-400",
};

function WorkersTable({ workers }: { workers: Worker[] }) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">Name</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Hosting</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Status</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Load</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Functions</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Processed</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Failed</th>
          <th className="px-3 py-2 text-left font-medium">Heartbeat</th>
        </tr>
      </thead>
      <tbody>
        {workers.map((worker) => {
          const style = statusStyles[worker.status];
          return (
            <tr key={worker.id} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
              <td className="matrix-cell px-3 py-2 mono text-[11px]">{worker.name}</td>
              <td className="matrix-cell px-3 py-2">
                <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", hostingStyles[worker.hosting])}>
                  {worker.hosting === "self-hosted" ? "SELF-HOSTED" : "MANAGED"}
                </span>
              </td>
              <td className="matrix-cell px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className={cn("w-2 h-2 rounded-full", style.dot)} />
                  <span className={cn("text-[10px] font-medium", style.text)}>
                    {worker.status.toUpperCase()}
                  </span>
                </div>
              </td>
              <td className="matrix-cell px-3 py-2">
                <div className="flex items-center gap-2">
                  <ProgressBar
                    value={worker.activeJobs}
                    max={worker.concurrency}
                    color="auto"
                    className="w-16"
                  />
                  <span className="mono text-[10px] text-[#666]">
                    {worker.activeJobs}/{worker.concurrency}
                  </span>
                </div>
              </td>
              <td className="matrix-cell px-3 py-2 text-[11px] text-[#888]">
                {worker.functions.length > 2
                  ? `${worker.functions.slice(0, 2).join(", ")} +${worker.functions.length - 2}`
                  : worker.functions.join(", ")}
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-emerald-400">
                {formatNumber(worker.jobsProcessed)}
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-red-400">
                {formatNumber(worker.jobsFailed)}
              </td>
              <td className="px-3 py-2 text-[11px] text-[#666]">{formatTimeAgo(worker.lastHeartbeat)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
