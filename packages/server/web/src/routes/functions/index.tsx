import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn, formatNumber, formatDuration } from "@/lib/utils";
import { getFunctions, queryKeys } from "@/lib/conduit-api";
import type { FunctionInfo, FunctionType } from "@/lib/types";
import { Search, X, ChevronDown } from "lucide-react";

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

  // Fetch functions from API
  const { data: functionsData } = useQuery({
    queryKey: queryKeys.functions({ type: selectedType || undefined }),
    queryFn: () => getFunctions({ type: selectedType || undefined }),
    refetchInterval: 30000, // Refresh every 30s
  });

  const allFunctions = functionsData?.functions ?? [];

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

    return fns;
  }, [allFunctions, search]);

  const clearFilters = () => {
    setSearch("");
    setSelectedType("");
  };

  const hasFilters = search || selectedType;

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
        <div className="h-full overflow-auto">
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
    </div>
  );
}

function FunctionsTable({ functions }: { functions: FunctionInfo[] }) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">Name</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Type</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">24H Runs</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Success</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Avg Duration</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Timeout</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Retries</th>
          <th className="px-3 py-2 text-left font-medium">Schedule/Pattern</th>
        </tr>
      </thead>
      <tbody>
        {functions.map((fn) => (
          <tr key={fn.name} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
            <td className="matrix-cell px-3 py-2 mono text-[11px]">{fn.name}</td>
            <td className="matrix-cell px-3 py-2">
              <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", typeStyles[fn.type])}>
                {fn.type.toUpperCase()}
              </span>
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px]">{formatNumber(fn.runs_24h)}</td>
            <td className="matrix-cell px-3 py-2 mono text-[11px]">
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
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">{formatDuration(fn.avg_duration_ms)}</td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#666]">{fn.timeout ?? "—"}s</td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#666]">{fn.max_retries ?? "—"}</td>
            <td className="px-3 py-2 mono text-[10px] text-[#555]">{fn.schedule || fn.pattern || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
