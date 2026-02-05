import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { generateMockApis, type Api } from "@/lib/mock-data";
import { Search, X, ChevronDown } from "lucide-react";

export const Route = createFileRoute("/apis/")({
  component: ApisPage,
});

type ApiStatus = "healthy" | "degraded" | "down";

const statusOptions: { value: ApiStatus | ""; label: string }[] = [
  { value: "", label: "All Statuses" },
  { value: "healthy", label: "Healthy" },
  { value: "degraded", label: "Degraded" },
  { value: "down", label: "Down" },
];

const statusStyles: Record<ApiStatus, { dot: string; text: string }> = {
  healthy: { dot: "bg-emerald-500", text: "text-emerald-400" },
  degraded: { dot: "bg-amber-500", text: "text-amber-400" },
  down: { dot: "bg-red-500", text: "text-red-400" },
};

function ApisPage() {
  const allApis = useMemo(() => generateMockApis(), []);
  const [search, setSearch] = useState("");
  const [selectedStatus, setSelectedStatus] = useState<ApiStatus | "">("");

  const filteredApis = useMemo(() => {
    let apis = allApis;

    if (search) {
      const searchLower = search.toLowerCase();
      apis = apis.filter((api) => api.name.toLowerCase().includes(searchLower));
    }

    if (selectedStatus) {
      apis = apis.filter((api) => api.status === selectedStatus);
    }

    return apis;
  }, [allApis, search, selectedStatus]);

  const clearFilters = () => {
    setSearch("");
    setSelectedStatus("");
  };

  const hasFilters = search || selectedStatus;

  // Calculate totals
  const totals = useMemo(() => {
    return filteredApis.reduce(
      (acc, api) => ({
        requestsPerMin: acc.requestsPerMin + api.requestsPerMin,
        avgLatency: acc.avgLatency + api.avgLatencyMs,
      }),
      { requestsPerMin: 0, avgLatency: 0 }
    );
  }, [filteredApis]);

  const avgLatency = filteredApis.length > 0 ? Math.round(totals.avgLatency / filteredApis.length) : 0;

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      {/* Filters Bar */}
      <div className="flex items-center gap-4 shrink-0">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555]" />
          <input
            type="text"
            placeholder="Search APIs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64 bg-[#1a1a1a] border border-[#2a2a2a] rounded-md pl-9 pr-3 py-2 text-sm text-[#e0e0e0] placeholder-[#555] focus:outline-none focus:border-[#3a3a3a]"
          />
        </div>

        {/* Status Filter */}
        <div className="relative">
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value as ApiStatus | "")}
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

        {/* Summary stats */}
        <div className="flex items-center gap-4 text-xs">
          <span className="text-[#555]">
            Total: <span className="mono text-[#888]">{totals.requestsPerMin.toLocaleString()} req/min</span>
          </span>
          <span className="text-[#555]">
            Avg Latency: <span className="mono text-[#888]">{avgLatency}ms</span>
          </span>
        </div>

        {/* Results count */}
        <span className="text-xs text-[#555] mono">
          {filteredApis.length} of {allApis.length} APIs
        </span>
      </div>

      {/* APIs Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        <div className="h-full overflow-auto">
          <ApisTable apis={filteredApis} />
        </div>
      </div>
    </div>
  );
}

const hostingStyles = {
  managed: "bg-sky-500/20 text-sky-400",
  "self-hosted": "bg-violet-500/20 text-violet-400",
};

function ApisTable({ apis }: { apis: Api[] }) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">Name</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Hosting</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Status</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Requests/min</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Avg Latency</th>
          <th className="px-3 py-2 text-left font-medium">Error Rate</th>
        </tr>
      </thead>
      <tbody>
        {apis.map((api) => {
          const style = statusStyles[api.status];
          return (
            <tr key={api.id} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
              <td className="matrix-cell px-3 py-2 mono text-[11px]">{api.name}</td>
              <td className="matrix-cell px-3 py-2">
                <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", hostingStyles[api.hosting])}>
                  {api.hosting === "self-hosted" ? "SELF-HOSTED" : "MANAGED"}
                </span>
              </td>
              <td className="matrix-cell px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className={cn("w-2 h-2 rounded-full", style.dot)} />
                  <span className={cn("text-[10px] font-medium", style.text)}>
                    {api.status.toUpperCase()}
                  </span>
                </div>
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">
                {api.requestsPerMin.toLocaleString()}
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">{api.avgLatencyMs}ms</td>
              <td className="px-3 py-2 mono text-[11px]">
                <span
                  className={cn(
                    api.errorRate === 0
                      ? "text-[#555]"
                      : api.errorRate < 1
                        ? "text-emerald-400"
                        : api.errorRate < 2
                          ? "text-amber-400"
                          : "text-red-400"
                  )}
                >
                  {api.errorRate}%
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
