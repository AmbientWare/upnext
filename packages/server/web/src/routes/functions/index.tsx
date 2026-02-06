import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn, formatNumber, formatDuration } from "@/lib/utils";
import { getFunctions, queryKeys } from "@/lib/conduit-api";
import type { FunctionInfo, FunctionType } from "@/lib/types";
import { Search, X, Circle } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

const typeOptions: { value: string; label: string }[] = [
  { value: "all", label: "All Types" },
  { value: "task", label: "Tasks" },
  { value: "cron", label: "Crons" },
  { value: "event", label: "Events" },
];

const typeStyles: Record<FunctionType, string> = {
  task: "bg-blue-500/20 text-blue-400",
  cron: "bg-violet-500/20 text-violet-400",
  event: "bg-amber-500/20 text-amber-400",
};

const STATUS_DEFAULT = "active";

function FunctionsPage() {
  const [search, setSearch] = useState("");
  const [selectedType, setSelectedType] = useState("all");
  const [selectedWorker, setSelectedWorker] = useState("all");
  const [statusFilter, setStatusFilter] = useState(STATUS_DEFAULT);

  const typeForQuery = selectedType === "all" ? undefined : (selectedType as FunctionType);

  // Fetch functions from API
  const { data: functionsData } = useQuery({
    queryKey: queryKeys.functions({ type: typeForQuery }),
    queryFn: () => getFunctions({ type: typeForQuery }),
    refetchInterval: 30000,
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
        {filteredFunctions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <div className="text-sm font-medium">No functions found</div>
            <div className="text-xs mt-1">
              {hasNonDefaultFilters ? "Try adjusting your filters" : "Functions will appear here when workers register"}
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
  const navigate = useNavigate();

  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Type</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Workers</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">24H Runs</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Success</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Avg Duration</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Timeout</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Retries</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Schedule/Pattern</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {functions.map((fn) => (
          <TableRow
            key={fn.name}
            className="border-border hover:bg-accent cursor-pointer"
            onClick={() => navigate({ to: "/functions/$name", params: { name: fn.name } })}
          >
            <TableCell className="py-2">
              <div className="flex items-center gap-2">
                <Circle className={cn("w-2 h-2 shrink-0", fn.active ? "fill-emerald-400 text-emerald-400" : "fill-muted-foreground/60 text-muted-foreground/60")} />
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
                    <span key={w} className="text-[10px] px-1.5 py-0.5 rounded bg-muted border border-input text-muted-foreground">
                      {w}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-[10px] text-muted-foreground/60">{"\u2014"}</span>
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
            <TableCell className="mono text-[11px] text-muted-foreground py-2">{formatDuration(fn.avg_duration_ms)}</TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">{fn.timeout ?? "\u2014"}s</TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">{fn.max_retries ?? "\u2014"}</TableCell>
            <TableCell className="mono text-[10px] text-muted-foreground py-2">{fn.schedule || fn.pattern || "\u2014"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
