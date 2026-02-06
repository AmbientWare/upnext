import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { getApis, queryKeys } from "@/lib/conduit-api";
import type { ApiInfo } from "@/lib/types";
import { Search, X } from "lucide-react";

export const Route = createFileRoute("/apis/")({
  component: ApisPage,
});

function ApisPage() {
  const [search, setSearch] = useState("");

  const { data: apisData } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: getApis,
    refetchInterval: 15000,
  });

  const allApis = apisData?.apis ?? [];

  const filteredApis = useMemo(() => {
    if (!search) return allApis;

    const searchLower = search.toLowerCase();
    return allApis.filter((api) =>
      api.name.toLowerCase().includes(searchLower)
    );
  }, [allApis, search]);

  // Calculate totals
  const totals = useMemo(() => {
    return filteredApis.reduce(
      (acc, api) => ({
        requestsPerMin: acc.requestsPerMin + api.requests_per_min,
        avgLatency: acc.avgLatency + api.avg_latency_ms,
      }),
      { requestsPerMin: 0, avgLatency: 0 }
    );
  }, [filteredApis]);

  const avgLatency = filteredApis.length > 0 ? Math.round(totals.avgLatency / filteredApis.length) : 0;
  const requestsPerMin = Math.round(totals.requestsPerMin);

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      {/* Filters Bar */}
      <div className="flex items-center gap-4 shrink-0">
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

        <div className="flex items-center gap-4 text-xs">
          <span className="text-[#555]">
            Total: <span className="mono text-[#888]">{requestsPerMin.toLocaleString()} req/min</span>
          </span>
          <span className="text-[#555]">
            Avg Latency: <span className="mono text-[#888]">{avgLatency}ms</span>
          </span>
        </div>

        <span className="text-xs text-[#555] mono">
          {filteredApis.length} of {allApis.length} APIs
        </span>
      </div>

      {/* APIs Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        <div className="h-full overflow-auto">
          {filteredApis.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-[#555]">
              <div className="text-sm font-medium">No APIs found</div>
              <div className="text-xs mt-1">
                {search ? "Try adjusting your search" : "APIs will appear here when requests are made"}
              </div>
            </div>
          ) : (
            <ApisTable apis={filteredApis} />
          )}
        </div>
      </div>
    </div>
  );
}

function ApisTable({ apis }: { apis: ApiInfo[] }) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">Name</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Endpoints</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Requests (24h)</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Avg Latency</th>
          <th className="px-3 py-2 text-left font-medium">Error Rate</th>
        </tr>
      </thead>
      <tbody>
        {apis.map((api) => (
          <tr key={api.name} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
            <td className="matrix-cell px-3 py-2 mono text-[11px]">{api.name}</td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">
              {api.endpoint_count}
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">
              {api.requests_24h.toLocaleString()}
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">{Math.round(api.avg_latency_ms)}ms</td>
            <td className="px-3 py-2 mono text-[11px]">
              <span
                className={cn(
                  api.error_rate === 0
                    ? "text-[#555]"
                    : api.error_rate < 1
                      ? "text-emerald-400"
                      : api.error_rate < 2
                        ? "text-amber-400"
                        : "text-red-400"
                )}
              >
                {api.error_rate.toFixed(1)}%
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
