import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn, statusConfig } from "@/lib/utils";
import { getJobs, getFunctions, queryKeys } from "@/lib/conduit-api";
import type { JobStatus } from "@/lib/types";
import { JobsTable, LiveIndicator } from "@/components/shared";
import { Search, X, ChevronDown } from "lucide-react";

export const Route = createFileRoute("/jobs/")({
  component: JobsPage,
});

const statusOptions: JobStatus[] = ["pending", "active", "complete", "failed", "cancelled", "retrying"];

type TimePeriod = "live" | "1h" | "24h" | "7d" | "30d" | "all";

const timePeriodOptions: { value: TimePeriod; label: string; hours?: number; limit?: number }[] = [
  { value: "live", label: "Live Feed", limit: 50 },
  { value: "1h", label: "Last Hour", hours: 1 },
  { value: "24h", label: "Last 24 Hours", hours: 24 },
  { value: "7d", label: "Last 7 Days", hours: 24 * 7 },
  { value: "30d", label: "Last 30 Days", hours: 24 * 30 },
  { value: "all", label: "All Time" },
];

function JobsPage() {
  const [search, setSearch] = useState("");
  const [selectedStatus, setSelectedStatus] = useState<JobStatus | "">("");
  const [selectedFunction, setSelectedFunction] = useState<string>("");
  const [selectedTimePeriod, setSelectedTimePeriod] = useState<TimePeriod>("live");
  const [timePeriodOpen, setTimePeriodOpen] = useState(false);
  const timePeriodRef = useRef<HTMLDivElement>(null);

  // Calculate query parameters based on filters
  const isLive = selectedTimePeriod === "live";
  const limit = isLive ? 50 : 200;

  // Fetch jobs from API
  const { data: jobsData, isFetching } = useQuery({
    queryKey: queryKeys.jobs({
      status: selectedStatus ? [selectedStatus] : undefined,
      function: selectedFunction || undefined,
      limit,
    }),
    queryFn: () =>
      getJobs({
        status: selectedStatus ? [selectedStatus] : undefined,
        function: selectedFunction || undefined,
        limit,
      }),
    refetchInterval: isLive ? 2000 : 30000, // Faster refresh for live mode
  });

  // Fetch functions list for filter dropdown
  const { data: functionsData } = useQuery({
    queryKey: queryKeys.functions(),
    queryFn: () => getFunctions(),
    staleTime: 60000, // Cache for 1 minute
  });

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (timePeriodRef.current && !timePeriodRef.current.contains(e.target as Node)) {
        setTimePeriodOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Get function names from API
  const functionNames = useMemo(() => {
    return functionsData?.functions.map((f) => f.name).sort() ?? [];
  }, [functionsData]);

  const jobs = jobsData?.jobs ?? [];
  const totalJobs = jobsData?.total ?? 0;

  const clearFilters = () => {
    setSearch("");
    setSelectedStatus("");
    setSelectedFunction("");
    setSelectedTimePeriod("live");
  };

  const hasFilters = search || selectedStatus || selectedFunction || selectedTimePeriod !== "live";

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      {/* Filters Bar */}
      <div className="flex items-center gap-4 shrink-0">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555]" />
          <input
            type="text"
            placeholder="Search jobs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64 bg-[#1a1a1a] border border-[#2a2a2a] rounded-md pl-9 pr-3 py-2 text-sm text-[#e0e0e0] placeholder-[#555] focus:outline-none focus:border-[#3a3a3a]"
          />
        </div>

        {/* Function Filter */}
        <div className="relative">
          <select
            value={selectedFunction}
            onChange={(e) => setSelectedFunction(e.target.value)}
            className={cn(
              "appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded-md px-3 py-2 pr-8 text-sm focus:outline-none focus:border-[#3a3a3a]",
              selectedFunction ? "text-[#e0e0e0]" : "text-[#555]"
            )}
          >
            <option value="">All Functions</option>
            {functionNames.map((fn) => (
              <option key={fn} value={fn}>
                {fn}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />
        </div>

        {/* Status Filter */}
        <div className="relative">
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value as JobStatus | "")}
            className={cn(
              "appearance-none bg-[#1a1a1a] border border-[#2a2a2a] rounded-md px-3 py-2 pr-8 text-sm focus:outline-none focus:border-[#3a3a3a]",
              selectedStatus ? "text-[#e0e0e0]" : "text-[#555]"
            )}
          >
            <option value="">All Statuses</option>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {statusConfig[status].label}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />
        </div>

        {/* Time Period Filter */}
        <div className="relative" ref={timePeriodRef}>
          <button
            onClick={() => setTimePeriodOpen(!timePeriodOpen)}
            className="flex items-center gap-2 bg-[#1a1a1a] border border-[#2a2a2a] rounded-md px-3 pr-8 text-sm text-[#e0e0e0] focus:outline-none focus:border-[#3a3a3a] min-w-[130px] h-[38px]"
          >
            {selectedTimePeriod === "live" ? (
              <LiveIndicator label={isFetching ? "Updating..." : "Live Feed"} size="md" />
            ) : (
              <span>{timePeriodOptions.find((p) => p.value === selectedTimePeriod)?.label}</span>
            )}
          </button>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />

          {timePeriodOpen && (
            <div className="absolute top-full left-0 mt-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-md py-1 min-w-full z-50 shadow-lg">
              {timePeriodOptions.map((p) => (
                <button
                  key={p.value}
                  onClick={() => {
                    setSelectedTimePeriod(p.value);
                    setTimePeriodOpen(false);
                  }}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-[#252525] transition-colors",
                    selectedTimePeriod === p.value ? "text-[#e0e0e0]" : "text-[#888]"
                  )}
                >
                  {p.value === "live" ? (
                    <LiveIndicator label="Live Feed" size="md" />
                  ) : (
                    <span>{p.label}</span>
                  )}
                </button>
              ))}
            </div>
          )}
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
          {isLive
            ? `Latest ${jobs.length} jobs`
            : `${jobs.length} of ${totalJobs} jobs`}
        </span>
      </div>

      {/* Jobs Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        <div className="h-full overflow-auto">
          {jobs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-[#555]">
              <div className="text-4xl mb-4">📋</div>
              <div className="text-sm font-medium">No jobs found</div>
              <div className="text-xs mt-1">
                {hasFilters ? "Try adjusting your filters" : "Jobs will appear here when they are created"}
              </div>
            </div>
          ) : (
            <JobsTable jobs={jobs} />
          )}
        </div>
      </div>
    </div>
  );
}
