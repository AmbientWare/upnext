import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatTimeAgo, formatNumber } from "@/lib/utils";
import { getWorkers, queryKeys } from "@/lib/conduit-api";
import type { Worker } from "@/lib/types";
import { Search, X } from "lucide-react";
import { ProgressBar } from "@/components/shared";

export const Route = createFileRoute("/workers/")({
  component: WorkersPage,
});

function WorkersPage() {
  const [search, setSearch] = useState("");

  // Fetch workers from API
  const { data: workersData } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: 10000, // Refresh every 10s
  });

  const allWorkers = workersData?.workers ?? [];

  const filteredWorkers = useMemo(() => {
    if (!search) return allWorkers;

    const searchLower = search.toLowerCase();
    return allWorkers.filter(
      (w) =>
        w.id.toLowerCase().includes(searchLower) ||
        w.functions.some((fn) => fn.toLowerCase().includes(searchLower))
    );
  }, [allWorkers, search]);

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

        {/* Clear Filters */}
        {search && (
          <button
            onClick={() => setSearch("")}
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
          {filteredWorkers.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-[#555]">
              <div className="text-sm font-medium">No workers found</div>
              <div className="text-xs mt-1">
                {search ? "Try adjusting your search" : "Workers will appear here when they register"}
              </div>
            </div>
          ) : (
            <WorkersTable workers={filteredWorkers} />
          )}
        </div>
      </div>
    </div>
  );
}

function WorkersTable({ workers }: { workers: Worker[] }) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">ID</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Load</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Functions</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Processed</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Failed</th>
          <th className="px-3 py-2 text-left font-medium">Heartbeat</th>
        </tr>
      </thead>
      <tbody>
        {workers.map((worker) => (
          <tr key={worker.id} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
            <td className="matrix-cell px-3 py-2 mono text-[11px]">{worker.id}</td>
            <td className="matrix-cell px-3 py-2">
              <div className="flex items-center gap-2">
                <ProgressBar
                  value={worker.active_jobs}
                  max={worker.concurrency}
                  color="auto"
                  className="w-16"
                />
                <span className="mono text-[10px] text-[#666]">
                  {worker.active_jobs}/{worker.concurrency}
                </span>
              </div>
            </td>
            <td className="matrix-cell px-3 py-2 text-[11px] text-[#888]">
              {worker.functions.length > 2
                ? `${worker.functions.slice(0, 2).join(", ")} +${worker.functions.length - 2}`
                : worker.functions.join(", ")}
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-emerald-400">
              {formatNumber(worker.jobs_processed)}
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-red-400">
              {formatNumber(worker.jobs_failed)}
            </td>
            <td className="px-3 py-2 text-[11px] text-[#666]">
              {formatTimeAgo(new Date(worker.last_heartbeat))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
