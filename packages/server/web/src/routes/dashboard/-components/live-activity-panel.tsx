import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { DateRange } from "react-day-picker";

import { getApiRequestEvents, getJobs, queryKeys } from "@/lib/upnext-api";
import type { Job } from "@/lib/types";
import {
  Panel,
  JobsTable,
  ApiRequestsTable,
  LiveWindowControls,
  getTimeWindowBounds,
  LIVE_LIST_LIMIT,
  LIVE_REFRESH_INTERVAL_MS,
  type TimeWindowPreset,
} from "@/components/shared";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface LiveActivityPanelProps {
  onJobClick?: (job: Job) => void;
  onApiClick?: (apiName: string) => void;
  className?: string;
}

const jobStatusOptions = [
  { value: "all", label: "All Status" },
  { value: "active", label: "Active" },
  { value: "complete", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "retrying", label: "Retrying" },
] as const;

function toTimestamp(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function jobTime(job: Job): number {
  return Math.max(
    toTimestamp(job.created_at),
    toTimestamp(job.scheduled_at),
    toTimestamp(job.started_at),
    toTimestamp(job.completed_at)
  );
}

export function LiveActivityPanel({
  onJobClick,
  onApiClick,
  className,
}: LiveActivityPanelProps) {
  const [activeTab, setActiveTab] = useState("jobs");
  const [live, setLive] = useState(true);
  const [windowPreset, setWindowPreset] = useState<TimeWindowPreset>("custom");
  const [dateRange, setDateRange] = useState<DateRange>();

  const [jobStatusFilter, setJobStatusFilter] = useState("all");
  const [jobWorkerFilter, setJobWorkerFilter] = useState("all");
  const [jobFunctionFilter, setJobFunctionFilter] = useState("all");

  const [apiNameFilter, setApiNameFilter] = useState("all");
  const [apiRouteFilter, setApiRouteFilter] = useState("all");
  const [apiStatusFilter, setApiStatusFilter] = useState("all");
  const [apiInstanceFilter, setApiInstanceFilter] = useState("all");

  const bounds = useMemo(() => {
    if (live) return null;
    return getTimeWindowBounds(windowPreset, dateRange);
  }, [dateRange, live, windowPreset]);

  const jobsQueryParams = useMemo(() => {
    if (live) {
      return { limit: LIVE_LIST_LIMIT };
    }
    if (!bounds) {
      return {};
    }
    return {
      after: bounds.from.toISOString(),
      before: bounds.to.toISOString(),
    };
  }, [bounds, live]);

  const jobsQueryKey = live
    ? queryKeys.jobs(jobsQueryParams)
    : (["dashboard", "live-activity", "jobs-window", jobsQueryParams] as const);

  const { data: jobsData, isPending: isJobsLoading } = useQuery({
    queryKey: jobsQueryKey,
    queryFn: () => getJobs(jobsQueryParams),
    refetchInterval: live ? LIVE_REFRESH_INTERVAL_MS : false,
    staleTime: live ? 0 : Number.POSITIVE_INFINITY,
  });

  const apiEventsQueryParams = live ? ({ limit: LIVE_LIST_LIMIT } as const) : ({} as const);

  const apiEventsQueryKey = live
    ? queryKeys.apiRequestEvents(apiEventsQueryParams)
    : (["dashboard", "live-activity", "api-events-window", apiEventsQueryParams] as const);

  const { data: apiEventsData, isPending: isApiLoading } = useQuery({
    queryKey: apiEventsQueryKey,
    queryFn: () => getApiRequestEvents(apiEventsQueryParams),
    refetchInterval: live ? LIVE_REFRESH_INTERVAL_MS : false,
    staleTime: live ? 0 : Number.POSITIVE_INFINITY,
  });

  const jobsInWindow = useMemo(() => {
    const sorted = [...(jobsData?.jobs ?? [])].sort((a, b) => jobTime(b) - jobTime(a));
    if (live) {
      return sorted.slice(0, LIVE_LIST_LIMIT);
    }
    return sorted;
  }, [jobsData?.jobs, live]);

  const jobWorkerOptions = useMemo(() => {
    const workers = new Set<string>();
    for (const job of jobsInWindow) {
      if (job.worker_id) workers.add(job.worker_id);
    }
    return [...workers].sort((a, b) => a.localeCompare(b));
  }, [jobsInWindow]);

  const jobFunctionOptions = useMemo(() => {
    const functions = new Set<string>();
    for (const job of jobsInWindow) {
      const functionName = job.function_name || job.function;
      if (functionName) functions.add(functionName);
    }
    return [...functions].sort((a, b) => a.localeCompare(b));
  }, [jobsInWindow]);

  const filteredJobs = useMemo(() => {
    return jobsInWindow.filter((job) => {
      if (jobStatusFilter !== "all" && job.status !== jobStatusFilter) return false;
      if (jobWorkerFilter !== "all" && (job.worker_id ?? "") !== jobWorkerFilter) return false;
      if (jobFunctionFilter !== "all" && (job.function_name || job.function) !== jobFunctionFilter) return false;
      return true;
    });
  }, [jobFunctionFilter, jobStatusFilter, jobWorkerFilter, jobsInWindow]);

  const apiEventsInWindow = useMemo(() => {
    const sorted = [...(apiEventsData?.events ?? [])].sort((a, b) => toTimestamp(b.at) - toTimestamp(a.at));
    if (live) {
      return sorted.slice(0, LIVE_LIST_LIMIT);
    }
    if (!bounds) {
      return sorted;
    }
    return sorted.filter((event) => {
      const at = toTimestamp(event.at);
      return at >= bounds.from.getTime() && at <= bounds.to.getTime();
    });
  }, [apiEventsData?.events, bounds, live]);

  const apiNameOptions = useMemo(() => {
    return [...new Set(apiEventsInWindow.map((event) => event.api_name))].sort((a, b) =>
      a.localeCompare(b)
    );
  }, [apiEventsInWindow]);

  const apiRouteOptions = useMemo(() => {
    return [...new Set(apiEventsInWindow.map((event) => `${event.method} ${event.path}`))].sort((a, b) =>
      a.localeCompare(b)
    );
  }, [apiEventsInWindow]);

  const apiStatusOptions = useMemo(() => {
    return [...new Set(apiEventsInWindow.map((event) => String(event.status)))].sort((a, b) =>
      Number(a) - Number(b)
    );
  }, [apiEventsInWindow]);

  const apiInstanceOptions = useMemo(() => {
    const set = new Set<string>();
    for (const event of apiEventsInWindow) {
      set.add(event.instance_id ?? "__none__");
    }
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [apiEventsInWindow]);

  const filteredApiRequestEvents = useMemo(() => {
    return apiEventsInWindow.filter((event) => {
      if (apiNameFilter !== "all" && event.api_name !== apiNameFilter) return false;
      if (apiRouteFilter !== "all" && `${event.method} ${event.path}` !== apiRouteFilter) return false;
      if (apiStatusFilter !== "all" && String(event.status) !== apiStatusFilter) return false;
      if (apiInstanceFilter !== "all") {
        if (apiInstanceFilter === "__none__") return !event.instance_id;
        return event.instance_id === apiInstanceFilter;
      }
      return true;
    });
  }, [apiEventsInWindow, apiInstanceFilter, apiNameFilter, apiRouteFilter, apiStatusFilter]);

  const jobsFilterControls = (
    <div className="flex items-center gap-1.5 flex-wrap justify-end">
      <Select value={jobStatusFilter} onValueChange={setJobStatusFilter}>
        <SelectTrigger size="sm" className="h-7 w-[120px] bg-muted border-input text-xs">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          {jobStatusOptions.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={jobWorkerFilter} onValueChange={setJobWorkerFilter}>
        <SelectTrigger size="sm" className="h-7 w-[130px] bg-muted border-input text-xs">
          <SelectValue placeholder="Worker" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Workers</SelectItem>
          {jobWorkerOptions.map((workerId) => (
            <SelectItem key={workerId} value={workerId}>
              {workerId}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={jobFunctionFilter} onValueChange={setJobFunctionFilter}>
        <SelectTrigger size="sm" className="h-7 w-[160px] bg-muted border-input text-xs">
          <SelectValue placeholder="Function" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Functions</SelectItem>
          {jobFunctionOptions.map((functionName) => (
            <SelectItem key={functionName} value={functionName}>
              {functionName}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <LiveWindowControls
        live={live}
        onLiveChange={setLive}
        preset={windowPreset}
        onPresetChange={setWindowPreset}
        dateRange={dateRange}
        onDateRangeChange={setDateRange}
      />
    </div>
  );

  const apiFilterControls = (
    <div className="flex items-center gap-1.5 flex-wrap justify-end">
      <Select value={apiNameFilter} onValueChange={setApiNameFilter}>
        <SelectTrigger size="sm" className="h-7 w-[130px] bg-muted border-input text-xs">
          <SelectValue placeholder="API" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All APIs</SelectItem>
          {apiNameOptions.map((apiName) => (
            <SelectItem key={apiName} value={apiName}>
              {apiName}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={apiRouteFilter} onValueChange={setApiRouteFilter}>
        <SelectTrigger size="sm" className="h-7 w-[170px] bg-muted border-input text-xs">
          <SelectValue placeholder="Route" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Routes</SelectItem>
          {apiRouteOptions.map((route) => (
            <SelectItem key={route} value={route}>
              {route}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={apiStatusFilter} onValueChange={setApiStatusFilter}>
        <SelectTrigger size="sm" className="h-7 w-[110px] bg-muted border-input text-xs">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Status</SelectItem>
          {apiStatusOptions.map((status) => (
            <SelectItem key={status} value={status}>
              {status}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={apiInstanceFilter} onValueChange={setApiInstanceFilter}>
        <SelectTrigger size="sm" className="h-7 w-[130px] bg-muted border-input text-xs">
          <SelectValue placeholder="Instance" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Instances</SelectItem>
          {apiInstanceOptions.map((instance) => (
            <SelectItem key={instance} value={instance}>
              {instance === "__none__" ? "No Instance" : instance}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <LiveWindowControls
        live={live}
        onLiveChange={setLive}
        preset={windowPreset}
        onPresetChange={setWindowPreset}
        dateRange={dateRange}
        onDateRangeChange={setDateRange}
      />
    </div>
  );

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full min-h-0">
      <Panel
        title="Live Activity"
        className={className ?? "flex-1 min-h-0 flex flex-col overflow-hidden"}
        contentClassName="flex-1 min-h-0 overflow-hidden p-0"
        titleCenter={
          <TabsList variant="line" className="h-8">
            <TabsTrigger value="jobs" className="text-xs">Jobs ({filteredJobs.length})</TabsTrigger>
            <TabsTrigger value="api-requests" className="text-xs">
              API Events ({filteredApiRequestEvents.length})
            </TabsTrigger>
          </TabsList>
        }
        titleRight={activeTab === "jobs" ? jobsFilterControls : apiFilterControls}
      >
        <div className="border-b border-border" />

        <TabsContent value="jobs" className="h-full min-h-0 m-0">
          <JobsTable
            jobs={filteredJobs}
            isLoading={isJobsLoading}
            onJobClick={onJobClick}
            className="h-full"
            emptyDescription="No jobs match your current filters."
          />
        </TabsContent>

        <TabsContent value="api-requests" className="h-full min-h-0 m-0">
          <ApiRequestsTable
            events={filteredApiRequestEvents}
            isLoading={isApiLoading}
            onApiClick={onApiClick}
            className="h-full"
            emptyDescription="No API events match your current filters."
          />
        </TabsContent>
      </Panel>
    </Tabs>
  );
}
