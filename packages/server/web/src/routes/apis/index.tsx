import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getApis, queryKeys } from "@/lib/conduit-api";
import { Search, X, Cloud } from "lucide-react";
import { useAnimatedNumber } from "@/hooks/use-animated-number";
import { ApisTableSkeleton } from "./-components/skeletons";
import { ApisTable } from "./-components/apis-table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/apis/")({
  component: ApisPage,
});

const STATUS_DEFAULT = "active";

function ApisPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(STATUS_DEFAULT);

  const { data: apisData, isPending } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: getApis,
    refetchInterval: 45000,
  });

  const allApis = useMemo(() => apisData?.apis ?? [], [apisData?.apis]);

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
  const animatedRequestsValue = useAnimatedNumber(requestsPerMin);
  const animatedLatency = useAnimatedNumber(avgLatency);
  const animatedRequests = Number.isNaN(Number(animatedRequestsValue))
    ? animatedRequestsValue
    : Number(animatedRequestsValue).toLocaleString();

  const hasNonDefaultFilters = search || statusFilter !== STATUS_DEFAULT;

  const clearFilters = () => {
    setSearch("");
    setStatusFilter(STATUS_DEFAULT);
  };

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      {/* Filters Bar */}
      <div className="shrink-0 space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 min-w-0 lg:flex-1">
            <div className="relative w-full sm:max-w-80">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search APIs..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full bg-muted border border-input rounded-md pl-9 pr-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-ring"
              />
            </div>

            {/* Status Filter */}
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger size="sm" className="w-full sm:w-[140px] bg-muted border-input text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="inactive">Inactive</SelectItem>
              </SelectContent>
            </Select>

            {hasNonDefaultFilters && (
              <button
                onClick={clearFilters}
                className="flex items-center gap-1 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors self-start sm:self-auto"
              >
                <X className="w-3 h-3" />
                Clear
              </button>
            )}
          </div>

          <span className="text-xs text-muted-foreground mono lg:text-right">
            {filteredApis.length} of {allApis.length} APIs
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="text-muted-foreground">
            Total: <span className="mono text-muted-foreground">{animatedRequests} req/min</span>
          </span>
          <span className="text-muted-foreground">
            Avg Latency: <span className="mono text-muted-foreground">{animatedLatency}ms</span>
          </span>
        </div>
      </div>

      {/* APIs Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        {isPending ? (
          <ApisTableSkeleton />
        ) : filteredApis.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <div className="rounded-full bg-muted/60 p-2 mb-2">
              <Cloud className="h-4 w-4" />
            </div>
            <div className="text-sm font-medium">No API traffic yet</div>
            <div className="text-xs mt-1 text-muted-foreground/80">
              {hasNonDefaultFilters ? "Try adjusting your filters" : "APIs will appear here once requests start flowing."}
            </div>
          </div>
        ) : (
          <ApisTable apis={filteredApis} />
        )}
      </div>
    </div>
  );
}
