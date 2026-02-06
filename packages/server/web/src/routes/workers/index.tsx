import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn, formatTimeAgo } from "@/lib/utils";
import { getWorkers, queryKeys } from "@/lib/conduit-api";
import type { WorkerInfo } from "@/lib/types";
import { Search, X, Circle } from "lucide-react";
import { ProgressBar } from "@/components/shared";
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

export const Route = createFileRoute("/workers/")({
  component: WorkersPage,
});

const STATUS_DEFAULT = "active";

function WorkersPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(STATUS_DEFAULT);

  const { data: workersData } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: getWorkers,
    refetchInterval: 10000,
  });

  const allWorkers = workersData?.workers ?? [];

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
      <div className="flex items-center gap-4 shrink-0">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search workers..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64 bg-muted border border-input rounded-md pl-9 pr-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-ring"
          />
        </div>

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

        <span className="text-xs text-muted-foreground mono">
          {filteredWorkers.length} of {allWorkers.length} workers
        </span>
      </div>

      {/* Workers Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        {filteredWorkers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <div className="text-sm font-medium">No workers found</div>
            <div className="text-xs mt-1">
              {hasNonDefaultFilters ? "Try adjusting your filters" : "Workers will appear here when they register"}
            </div>
          </div>
        ) : (
          <WorkersTable workers={filteredWorkers} />
        )}
      </div>
    </div>
  );
}

function WorkersTable({ workers }: { workers: WorkerInfo[] }) {
  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Instances</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Functions</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Concurrency</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {workers.map((worker) => (
          <TableRow key={worker.name} className="border-border hover:bg-accent">
            <TableCell className="py-2">
              <div className="flex items-center gap-2">
                <Circle className={cn("w-2 h-2 shrink-0", worker.active ? "fill-emerald-400 text-emerald-400" : "fill-muted-foreground/60 text-muted-foreground/60")} />
                <span className="text-[11px] text-foreground">{worker.name}</span>
              </div>
            </TableCell>
            <TableCell className="py-2">
              {worker.instances.length > 0 ? (
                <div className="flex flex-col gap-0.5">
                  {worker.instances.map((inst) => (
                    <div key={inst.id} className="flex items-center gap-1.5">
                      <span className="mono text-[10px] text-muted-foreground">{inst.id}</span>
                      <div className="flex items-center gap-1">
                        <ProgressBar
                          value={inst.active_jobs}
                          max={inst.concurrency}
                          color="auto"
                          className="w-12"
                        />
                        <span className="mono text-[10px] text-muted-foreground">
                          {inst.active_jobs}/{inst.concurrency}
                        </span>
                      </div>
                      <span className="text-[10px] text-muted-foreground/60">
                        {formatTimeAgo(new Date(inst.last_heartbeat))}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="text-[10px] text-muted-foreground/60">{"\u2014"}</span>
              )}
            </TableCell>
            <TableCell className="text-[11px] text-muted-foreground py-2">
              {worker.functions.length > 3
                ? `${worker.functions.slice(0, 3).join(", ")} +${worker.functions.length - 3}`
                : worker.functions.join(", ")}
            </TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">
              {worker.concurrency}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
