import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, useRef, useEffect } from "react";
import { cn, type JobStatus, statusConfig } from "@/lib/utils";
import { generateMockJobs } from "@/lib/mock-data";
import { JobsTable, LiveIndicator } from "@/components/shared";
import { Search, X, ChevronDown } from "lucide-react";

export const Route = createFileRoute("/jobs/")({
  component: JobsPage,
});

const statusOptions: JobStatus[] = ["pending", "queued", "active", "complete", "failed", "cancelled", "retrying"];

type TimePeriod = "live" | "1h" | "24h" | "7d" | "30d" | "all";

const timePeriodOptions: { value: TimePeriod; label: string; ms: number; limit?: number }[] = [
  { value: "live", label: "Live Feed", ms: 0, limit: 50 },
  { value: "1h", label: "Last Hour", ms: 60 * 60 * 1000 },
  { value: "24h", label: "Last 24 Hours", ms: 24 * 60 * 60 * 1000 },
  { value: "7d", label: "Last 7 Days", ms: 7 * 24 * 60 * 60 * 1000 },
  { value: "30d", label: "Last 30 Days", ms: 30 * 24 * 60 * 60 * 1000 },
  { value: "all", label: "All Time", ms: 0 },
];

function JobsPage() {
  const allJobs = useMemo(() => {
    // Sort by scheduledAt descending (newer first)
    return generateMockJobs(200).sort((a, b) => b.scheduledAt.getTime() - a.scheduledAt.getTime());
  }, []);
  const [search, setSearch] = useState("");
  const [selectedStatus, setSelectedStatus] = useState<JobStatus | "">("");
  const [selectedFunction, setSelectedFunction] = useState<string>("");
  const [selectedTimePeriod, setSelectedTimePeriod] = useState<TimePeriod>("live");
  const [timePeriodOpen, setTimePeriodOpen] = useState(false);
  const timePeriodRef = useRef<HTMLDivElement>(null);

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

  // Get unique function names
  const functionNames = useMemo(() => {
    const names = new Set(allJobs.map((job) => job.function));
    return Array.from(names).sort();
  }, [allJobs]);

  const filteredJobs = useMemo(() => {
    let jobs = allJobs;

    // Filter by search
    if (search) {
      const searchLower = search.toLowerCase();
      jobs = jobs.filter(
        (job) =>
          job.id.toLowerCase().includes(searchLower) ||
          job.function.toLowerCase().includes(searchLower) ||
          job.workerId?.toLowerCase().includes(searchLower)
      );
    }

    // Filter by status
    if (selectedStatus) {
      jobs = jobs.filter((job) => job.status === selectedStatus);
    }

    // Filter by function
    if (selectedFunction) {
      jobs = jobs.filter((job) => job.function === selectedFunction);
    }

    // Filter by time period
    const period = timePeriodOptions.find((p) => p.value === selectedTimePeriod);
    if (period) {
      if (period.limit) {
        // Live feed mode - just take the latest N jobs
        jobs = jobs.slice(0, period.limit);
      } else if (period.ms > 0) {
        // Time-based filter
        const cutoff = new Date(Date.now() - period.ms);
        jobs = jobs.filter((job) => job.scheduledAt >= cutoff);
      }
    }

    return jobs;
  }, [allJobs, search, selectedStatus, selectedFunction, selectedTimePeriod]);

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
              <LiveIndicator label="Live Feed" size="md" />
            ) : (
              <span>{timePeriodOptions.find((p) => p.value === selectedTimePeriod)?.label}</span>
            )}
          </button>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-[#555] pointer-events-none" />

          {timePeriodOpen && (
            <div className="absolute top-full left-0 mt-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-md py-1 min-w-full z-50 shadow-lg">
              {timePeriodOptions.map((period) => (
                <button
                  key={period.value}
                  onClick={() => {
                    setSelectedTimePeriod(period.value);
                    setTimePeriodOpen(false);
                  }}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-[#252525] transition-colors",
                    selectedTimePeriod === period.value ? "text-[#e0e0e0]" : "text-[#888]"
                  )}
                >
                  {period.value === "live" ? (
                    <LiveIndicator label="Live Feed" size="md" />
                  ) : (
                    <span>{period.label}</span>
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
          {selectedTimePeriod === "live"
            ? `Latest ${filteredJobs.length} jobs`
            : `${filteredJobs.length} of ${allJobs.length} jobs`}
        </span>
      </div>

      {/* Jobs Table */}
      <div className="matrix-panel rounded flex-1 overflow-hidden">
        <div className="h-full overflow-auto">
          <JobsTable jobs={filteredJobs} />
        </div>
      </div>
    </div>
  );
}
