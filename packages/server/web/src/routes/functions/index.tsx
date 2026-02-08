import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getFunctions, queryKeys } from "@/lib/conduit-api";
import type { FunctionType } from "@/lib/types";
import { Search, X, FunctionSquare } from "lucide-react";
import { FunctionsTableSkeleton } from "./-components/skeletons";
import { FunctionsTable } from "./-components/functions-table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/functions/")({
  component: FunctionsPage,
});

const typeOptions: { value: string; label: string }[] = [
  { value: "all", label: "All Types" },
  { value: "task", label: "Tasks" },
  { value: "cron", label: "Crons" },
  { value: "event", label: "Events" },
];

const STATUS_DEFAULT = "active";

function FunctionsPage() {
  const [search, setSearch] = useState("");
  const [selectedType, setSelectedType] = useState("all");
  const [selectedWorker, setSelectedWorker] = useState("all");
  const [statusFilter, setStatusFilter] = useState(STATUS_DEFAULT);

  const typeForQuery = selectedType === "all" ? undefined : (selectedType as FunctionType);

  // Fetch functions from API
  const { data: functionsData, isPending } = useQuery({
    queryKey: queryKeys.functions({ type: typeForQuery }),
    queryFn: () => getFunctions({ type: typeForQuery }),
    refetchInterval: 30000,
  });

  const allFunctions = useMemo(() => functionsData?.functions ?? [], [functionsData?.functions]);

  // Extract unique worker names for filter dropdown
  const workerOptions = useMemo(() => {
    const names = new Set<string>();
    for (const fn of allFunctions) {
      for (const w of fn.workers ?? []) names.add(w);
    }
    return Array.from(names).sort();
  }, [allFunctions]);

  const filteredFunctions = useMemo(() => {
    let fns = allFunctions;

    if (search) {
      const searchLower = search.toLowerCase();
      fns = fns.filter(
        (fn) =>
          fn.name.toLowerCase().includes(searchLower) ||
          fn.schedule?.toLowerCase().includes(searchLower) ||
          fn.pattern?.toLowerCase().includes(searchLower)
      );
    }

    if (selectedWorker !== "all") {
      fns = fns.filter((fn) => (fn.workers ?? []).includes(selectedWorker));
    }

    if (statusFilter === "active") {
      fns = fns.filter((fn) => fn.active);
    } else if (statusFilter === "inactive") {
      fns = fns.filter((fn) => !fn.active);
    }

    return fns;
  }, [allFunctions, search, selectedWorker, statusFilter]);

  const hasNonDefaultFilters = search || selectedType !== "all" || selectedWorker !== "all" || statusFilter !== STATUS_DEFAULT;

  const clearFilters = () => {
    setSearch("");
    setSelectedType("all");
    setSelectedWorker("all");
    setStatusFilter(STATUS_DEFAULT);
  };

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      {/* Filters Bar */}
      <div className="flex items-center gap-4 shrink-0">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search functions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64 bg-muted border border-input rounded-md pl-9 pr-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-ring"
          />
        </div>

        {/* Type Filter */}
        <Select value={selectedType} onValueChange={setSelectedType}>
          <SelectTrigger size="sm" className="w-[120px] bg-muted border-input text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {typeOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Worker Filter */}
        {workerOptions.length > 0 && (
          <Select value={selectedWorker} onValueChange={setSelectedWorker}>
            <SelectTrigger size="sm" className="w-[160px] bg-muted border-input text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Workers</SelectItem>
              {workerOptions.map((w) => (
                <SelectItem key={w} value={w}>{w}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {/* Status Filter */}
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger size="sm" className="w-[120px] bg-muted border-input text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
          </SelectContent>
        </Select>

        {/* Clear Filters */}
        {hasNonDefaultFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-3 h-3" />
            Clear
          </button>
        )}

        <div className="flex-1" />

        {/* Results count */}
        <span className="text-xs text-muted-foreground mono">
          {filteredFunctions.length} of {allFunctions.length} functions
        </span>
      </div>

      {/* Functions Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        {isPending ? (
          <FunctionsTableSkeleton />
        ) : filteredFunctions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <div className="rounded-full bg-muted/60 p-2 mb-2">
              <FunctionSquare className="h-4 w-4" />
            </div>
            <div className="text-sm font-medium">No functions available</div>
            <div className="text-xs mt-1 text-muted-foreground/80">
              {hasNonDefaultFilters ? "Try adjusting your filters" : "Functions will appear here when workers register with Conduit."}
            </div>
          </div>
        ) : (
          <FunctionsTable functions={filteredFunctions} />
        )}
      </div>
    </div>
  );
}
