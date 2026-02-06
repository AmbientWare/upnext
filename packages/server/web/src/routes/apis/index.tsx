import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn, formatTimeAgo } from "@/lib/utils";
import { getApis, queryKeys } from "@/lib/conduit-api";
import type { ApiInfo } from "@/lib/types";
import { Search, X, ChevronDown, Circle } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/apis/")({
  component: ApisPage,
});

function ApisPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "active" | "inactive">("");

  const { data: apisData } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: getApis,
    refetchInterval: 15000,
  });

  const allApis = apisData?.apis ?? [];

  const filteredApis = useMemo(() => {
    let apis = allApis;

    if (search) {
      const searchLower = search.toLowerCase();
      apis = apis.filter((api) => api.name.toLowerCase().includes(searchLower));
    }

    if (statusFilter === "active") {
      apis = apis.filter((api) => api.active);
    } else if (statusFilter === "inactive") {
      apis = apis.filter((api) => !api.active);
    }

    return apis;
  }, [allApis, search, statusFilter]);

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

        {/* Status Filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "" | "active" | "inactive")}
            className={cn(
              "appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded-md px-3 py-2 pr-8 text-sm focus:outline-none focus:border-[#3a3a3a]",
              statusFilter ? "text-[#e0e0e0]" : "text-[#555]"
            )}
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />
        </div>

        {(search || statusFilter) && (
          <button
            onClick={() => { setSearch(""); setStatusFilter(""); }}
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
  );
}

function ApisTable({ apis }: { apis: ApiInfo[] }) {
  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-[#141414]">
        <TableRow className="text-[10px] text-[#666] uppercase tracking-wider border-[#2a2a2a] hover:bg-transparent">
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Instances</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Endpoints</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Requests (24h)</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Avg Latency</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Error Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {apis.map((api) => (
          <TableRow key={api.name} className="border-[#1e1e1e] hover:bg-[#1a1a1a]">
            <TableCell className="py-2">
              <div className="flex items-center gap-2">
                <Circle className={cn("w-2 h-2 shrink-0", api.active ? "fill-emerald-400 text-emerald-400" : "fill-[#444] text-[#444]")} />
                <span className="text-[11px] text-[#e0e0e0]">{api.name}</span>
              </div>
            </TableCell>
            <TableCell className="py-2">
              {(api.instances ?? []).length > 0 ? (
                <div className="flex flex-col gap-0.5">
                  {(api.instances ?? []).map((inst) => (
                    <div key={inst.id} className="flex items-center gap-1.5">
                      <span className="mono text-[10px] text-[#888]">{inst.id}</span>
                      <span className="text-[10px] text-[#555]">
                        {inst.host}:{inst.port}
                      </span>
                      <span className="text-[10px] text-[#444]">
                        {formatTimeAgo(new Date(inst.last_heartbeat))}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="text-[10px] text-[#444]">{"\u2014"}</span>
              )}
            </TableCell>
            <TableCell className="mono text-[11px] text-[#888] py-2">
              {api.endpoint_count}
            </TableCell>
            <TableCell className="mono text-[11px] text-[#888] py-2">
              {api.requests_24h.toLocaleString()}
            </TableCell>
            <TableCell className="mono text-[11px] text-[#888] py-2">{Math.round(api.avg_latency_ms)}ms</TableCell>
            <TableCell className="mono text-[11px] py-2">
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
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
