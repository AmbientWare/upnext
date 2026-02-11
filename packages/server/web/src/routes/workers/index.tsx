import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getWorkers, queryKeys } from "@/lib/upnext-api";
import { Search, X, Server } from "lucide-react";
import { WorkersTableSkeleton } from "./-components/skeletons";
import { WorkersTable } from "./-components/workers-table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/workers/")({
  component: WorkersPage,
});

const WORKERS_SAFETY_RESYNC_MS = 10 * 60 * 1000;

const STATUS_DEFAULT = "active";

function WorkersPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(STATUS_DEFAULT);

  const { data: workersData, isPending } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: WORKERS_SAFETY_RESYNC_MS,
  });

  const allWorkers = useMemo(() => workersData?.workers ?? [], [workersData?.workers]);

  const filteredWorkers = useMemo(() => {
    let workers = allWorkers;

    if (search) {
      const searchLower = search.toLowerCase();
      workers = workers.filter(
        (w) =>
          w.name.toLowerCase().includes(searchLower) ||
          w.functions.some((fn) => fn.toLowerCase().includes(searchLower))
      );
    }

    if (statusFilter === "active") {
      workers = workers.filter((w) => w.active);
    } else if (statusFilter === "inactive") {
      workers = workers.filter((w) => !w.active);
    }

    return workers;
  }, [allWorkers, search, statusFilter]);

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
                placeholder="Search workers..."
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
            {filteredWorkers.length} of {allWorkers.length} workers
          </span>
        </div>
      </div>

      {/* Workers Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        {isPending ? (
          <WorkersTableSkeleton />
        ) : filteredWorkers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <div className="rounded-full bg-muted/60 p-2 mb-2">
              <Server className="h-4 w-4" />
            </div>
            <div className="text-sm font-medium">No workers connected</div>
            <div className="text-xs mt-1 text-muted-foreground/80">
              {hasNonDefaultFilters ? "Try adjusting your filters" : "Workers will appear here when they register with UpNext."}
            </div>
          </div>
        ) : (
          <WorkersTable workers={filteredWorkers} />
        )}
      </div>
    </div>
  );
}
