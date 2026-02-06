import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn, formatNumber, formatDuration } from "@/lib/utils";
import { getFunctions, queryKeys } from "@/lib/conduit-api";
import type { FunctionInfo, FunctionType } from "@/lib/types";
import { Search, X, ChevronDown, Circle } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/functions/")({
  component: FunctionsPage,
});

const typeOptions: { value: FunctionType | ""; label: string }[] = [
  { value: "", label: "All Types" },
  { value: "task", label: "Tasks" },
  { value: "cron", label: "Crons" },
  { value: "event", label: "Events" },
];

const typeStyles: Record<FunctionType, string> = {
  task: "bg-blue-500/20 text-blue-400",
  cron: "bg-violet-500/20 text-violet-400",
  event: "bg-amber-500/20 text-amber-400",
};

function FunctionsPage() {
  const [search, setSearch] = useState("");
  const [selectedType, setSelectedType] = useState<FunctionType | "">("");
  const [selectedWorker, setSelectedWorker] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "active" | "inactive">("");

  // Fetch functions from API
  const { data: functionsData } = useQuery({
    queryKey: queryKeys.functions({ type: selectedType || undefined }),
    queryFn: () => getFunctions({ type: selectedType || undefined }),
    refetchInterval: 30000, // Refresh every 30s
  });

  const allFunctions = functionsData?.functions ?? [];

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

    if (selectedWorker) {
      fns = fns.filter((fn) => (fn.workers ?? []).includes(selectedWorker));
    }

    if (statusFilter === "active") {
      fns = fns.filter((fn) => fn.active);
    } else if (statusFilter === "inactive") {
      fns = fns.filter((fn) => !fn.active);
    }

    return fns;
  }, [allFunctions, search, selectedWorker, statusFilter]);

  const clearFilters = () => {
    setSearch("");
    setSelectedType("");
    setSelectedWorker("");
    setStatusFilter("");
  };

  const hasFilters = search || selectedType || selectedWorker || statusFilter;

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      {/* Filters Bar */}
      <div className="flex items-center gap-4 shrink-0">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555]" />
          <input
            type="text"
            placeholder="Search functions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64 bg-[#1a1a1a] border border-[#2a2a2a] rounded-md pl-9 pr-3 py-2 text-sm text-[#e0e0e0] placeholder-[#555] focus:outline-none focus:border-[#3a3a3a]"
          />
        </div>

        {/* Type Filter */}
        <div className="relative">
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value as FunctionType | "")}
            className={cn(
              "appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded-md px-3 py-2 pr-8 text-sm focus:outline-none focus:border-[#3a3a3a]",
              selectedType ? "text-[#e0e0e0]" : "text-[#555]"
            )}
          >
            {typeOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />
        </div>

        {/* Worker Filter */}
        {workerOptions.length > 0 && (
          <div className="relative">
            <select
              value={selectedWorker}
              onChange={(e) => setSelectedWorker(e.target.value)}
              className={cn(
                "appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded-md px-3 py-2 pr-8 text-sm focus:outline-none focus:border-[#3a3a3a]",
                selectedWorker ? "text-[#e0e0e0]" : "text-[#555]"
              )}
            >
              <option value="">All Workers</option>
              {workerOptions.map((w) => (
                <option key={w} value={w}>{w}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />
          </div>
        )}

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
          {filteredFunctions.length} of {allFunctions.length} functions
        </span>
      </div>

      {/* Functions Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        {filteredFunctions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-[#555]">
            <div className="text-4xl mb-4">⚡</div>
            <div className="text-sm font-medium">No functions found</div>
            <div className="text-xs mt-1">
              {hasFilters ? "Try adjusting your filters" : "Functions will appear here when workers register"}
            </div>
          </div>
        ) : (
          <FunctionsTable functions={filteredFunctions} />
        )}
      </div>
    </div>
  );
}

function FunctionsTable({ functions }: { functions: FunctionInfo[] }) {
  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-[#141414]">
        <TableRow className="text-[10px] text-[#666] uppercase tracking-wider border-[#2a2a2a] hover:bg-transparent">
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Type</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Workers</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">24H Runs</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Success</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Avg Duration</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Timeout</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Retries</TableHead>
          <TableHead className="text-[10px] text-[#666] font-medium h-8">Schedule/Pattern</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {functions.map((fn) => (
          <TableRow key={fn.name} className="border-[#1e1e1e] hover:bg-[#1a1a1a]">
            <TableCell className="py-2">
              <div className="flex items-center gap-2">
                <Circle className={cn("w-2 h-2 shrink-0", fn.active ? "fill-emerald-400 text-emerald-400" : "fill-[#444] text-[#444]")} />
                <span className="mono text-[11px]">{fn.name}</span>
              </div>
            </TableCell>
            <TableCell className="py-2">
              <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", typeStyles[fn.type])}>
                {fn.type.toUpperCase()}
              </span>
            </TableCell>
            <TableCell className="py-2">
              {(fn.workers ?? []).length > 0 ? (
                <div className="flex items-center gap-1 flex-wrap">
                  {(fn.workers ?? []).map((w) => (
                    <span key={w} className="text-[10px] px-1.5 py-0.5 rounded bg-[#1a1a1a] border border-[#2a2a2a] text-[#888]">
                      {w}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-[10px] text-[#444]">{"\u2014"}</span>
              )}
            </TableCell>
            <TableCell className="mono text-[11px] py-2">{formatNumber(fn.runs_24h)}</TableCell>
            <TableCell className="mono text-[11px] py-2">
              <span
                className={cn(
                  fn.success_rate >= 99
                    ? "text-emerald-400"
                    : fn.success_rate >= 95
                      ? "text-amber-400"
                      : "text-red-400"
                )}
              >
                {fn.success_rate.toFixed(1)}%
              </span>
            </TableCell>
            <TableCell className="mono text-[11px] text-[#888] py-2">{formatDuration(fn.avg_duration_ms)}</TableCell>
            <TableCell className="mono text-[11px] text-[#666] py-2">{fn.timeout ?? "\u2014"}s</TableCell>
            <TableCell className="mono text-[11px] text-[#666] py-2">{fn.max_retries ?? "\u2014"}</TableCell>
            <TableCell className="mono text-[10px] text-[#555] py-2">{fn.schedule || fn.pattern || "\u2014"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
