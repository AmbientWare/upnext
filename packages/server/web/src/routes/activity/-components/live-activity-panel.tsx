import { useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { DateRange } from "react-day-picker";
import { RotateCcw, X } from "lucide-react";
import { toast } from "sonner";

import {
  cancelJob,
  getApis,
  getApiRequestEvents,
  getFunctions,
  getJobs,
  getWorkers,
  queryKeys,
  retryJob,
  type GetApiRequestEventsParams,
  type GetJobsParams,
} from "@/lib/upnext-api";
import type { Job } from "@/lib/types";
import {
  Panel,
  JobsTable,
  ApiRequestsTable,
  LiveWindowControls,
  getTimeWindowBounds,
  LIVE_LIST_LIMIT,
  type TimeWindowPreset,
} from "@/components/shared";
import { Button } from "@/components/ui/button";
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
  { value: "pending", label: "Pending" },
  { value: "queued", label: "Queued" },
  { value: "active", label: "Active" },
  { value: "complete", label: "Complete" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "retrying", label: "Retrying" },
] as const;

const RETRYABLE_STATUSES = new Set(["failed", "cancelled"]);
const CANCELLABLE_STATUSES = new Set(["pending", "queued", "active", "retrying"]);
const LIVE_POLL_FALLBACK_MS = 5_000;
const WINDOW_PAGE_SIZE = 100;

function parseRouteFilter(route: string): { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; path?: string } {
  if (route === "all") return {};
  const [methodPart, ...pathParts] = route.split(" ");
  const method = methodPart?.toUpperCase() as "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  const path = pathParts.join(" ").trim();
  if (!method || !path) return {};
  return { method, path };
}

export function LiveActivityPanel({
  onJobClick,
  onApiClick,
  className,
}: LiveActivityPanelProps) {
  const queryClient = useQueryClient();
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

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboardStats });
    },
    onError: (error: unknown) => {
      toast.error(error instanceof Error ? error.message : "Failed to cancel job");
    },
  });

  const retryMutation = useMutation({
    mutationFn: (jobId: string) => retryJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboardStats });
    },
    onError: (error: unknown) => {
      toast.error(error instanceof Error ? error.message : "Failed to retry job");
    },
  });

  const bounds = useMemo(() => {
    if (live) return null;
    return getTimeWindowBounds(windowPreset, dateRange);
  }, [dateRange, live, windowPreset]);

  const { data: functionsData } = useQuery({
    queryKey: queryKeys.functions(),
    queryFn: () => getFunctions(),
    staleTime: 60_000,
  });

  const { data: workersData } = useQuery({
    queryKey: queryKeys.workers,
    queryFn: () => getWorkers(),
    staleTime: 15_000,
  });

  const { data: apisData } = useQuery({
    queryKey: queryKeys.apis,
    queryFn: () => getApis(),
    staleTime: 30_000,
  });

  const jobsFilters = useMemo<GetJobsParams>(() => {
    return {
      function: jobFunctionFilter === "all" ? undefined : jobFunctionFilter,
      worker_id: jobWorkerFilter === "all" ? undefined : jobWorkerFilter,
      status: jobStatusFilter === "all" ? undefined : [jobStatusFilter],
    };
  }, [jobFunctionFilter, jobStatusFilter, jobWorkerFilter]);

  const jobsLiveParams = useMemo<GetJobsParams>(
    () => ({ ...jobsFilters, limit: LIVE_LIST_LIMIT }),
    [jobsFilters]
  );

  const jobsWindowParams = useMemo<GetJobsParams>(() => {
    if (!bounds) return jobsFilters;
    return {
      ...jobsFilters,
      after: bounds.from.toISOString(),
      before: bounds.to.toISOString(),
    };
  }, [bounds, jobsFilters]);

  const { data: liveJobsData, isPending: isLiveJobsLoading } = useQuery({
    queryKey: queryKeys.jobs(jobsLiveParams),
    queryFn: () => getJobs(jobsLiveParams),
    refetchInterval: live ? LIVE_POLL_FALLBACK_MS : false,
    staleTime: live ? 0 : Number.POSITIVE_INFINITY,
    enabled: live,
  });

  const {
    data: windowJobsData,
    isPending: isWindowJobsLoading,
    hasNextPage: jobsHasNextPage,
    fetchNextPage: fetchNextJobsPage,
    isFetchingNextPage: isFetchingNextJobsPage,
  } = useInfiniteQuery({
    queryKey: ["activity", "jobs-window", jobsWindowParams],
    queryFn: ({ pageParam }) =>
      getJobs({
        ...jobsWindowParams,
        limit: WINDOW_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage.has_more) return undefined;
      return allPages.reduce((sum, page) => sum + page.jobs.length, 0);
    },
    enabled: !live && Boolean(bounds),
    staleTime: Number.POSITIVE_INFINITY,
  });

  const routeFilter = useMemo(() => parseRouteFilter(apiRouteFilter), [apiRouteFilter]);
  const apiStatusNumber = useMemo(
    () => (apiStatusFilter === "all" ? undefined : Number(apiStatusFilter)),
    [apiStatusFilter]
  );

  const apiFilters = useMemo<GetApiRequestEventsParams>(() => {
    return {
      api_name: apiNameFilter === "all" ? undefined : apiNameFilter,
      method: routeFilter.method,
      path: routeFilter.path,
      status: Number.isFinite(apiStatusNumber) ? apiStatusNumber : undefined,
      instance_id: apiInstanceFilter === "all" ? undefined : apiInstanceFilter,
    };
  }, [apiInstanceFilter, apiNameFilter, apiStatusNumber, routeFilter.method, routeFilter.path]);

  const apiLiveParams = useMemo<GetApiRequestEventsParams>(
    () => ({ ...apiFilters, limit: LIVE_LIST_LIMIT }),
    [apiFilters]
  );

  const apiWindowParams = useMemo<GetApiRequestEventsParams>(() => {
    if (!bounds) return apiFilters;
    return {
      ...apiFilters,
      after: bounds.from.toISOString(),
      before: bounds.to.toISOString(),
    };
  }, [apiFilters, bounds]);

  const { data: liveApiEventsData, isPending: isLiveApiLoading } = useQuery({
    queryKey: queryKeys.apiRequestEvents(apiLiveParams),
    queryFn: () => getApiRequestEvents(apiLiveParams),
    refetchInterval: live ? LIVE_POLL_FALLBACK_MS : false,
    staleTime: live ? 0 : Number.POSITIVE_INFINITY,
    enabled: live,
  });

  const {
    data: windowApiEventsData,
    isPending: isWindowApiLoading,
    hasNextPage: apiHasNextPage,
    fetchNextPage: fetchNextApiEventsPage,
    isFetchingNextPage: isFetchingNextApiEventsPage,
  } = useInfiniteQuery({
    queryKey: ["activity", "api-events-window", apiWindowParams],
    queryFn: ({ pageParam }) =>
      getApiRequestEvents({
        ...apiWindowParams,
        limit: WINDOW_PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage.has_more) return undefined;
      return allPages.reduce((sum, page) => sum + page.events.length, 0);
    },
    enabled: !live && Boolean(bounds),
    staleTime: Number.POSITIVE_INFINITY,
  });

  const jobs = useMemo(() => {
    const rows = live
      ? (liveJobsData?.jobs ?? [])
      : (windowJobsData?.pages.flatMap((page) => page.jobs) ?? []);
    return rows;
  }, [live, liveJobsData?.jobs, windowJobsData?.pages]);

  const jobsTotal = useMemo(() => {
    if (live) return liveJobsData?.total ?? jobs.length;
    return windowJobsData?.pages[0]?.total ?? 0;
  }, [jobs.length, live, liveJobsData?.total, windowJobsData?.pages]);

  const apiEvents = useMemo(() => {
    const rows = live
      ? (liveApiEventsData?.events ?? [])
      : (windowApiEventsData?.pages.flatMap((page) => page.events) ?? []);
    return rows;
  }, [live, liveApiEventsData?.events, windowApiEventsData?.pages]);

  const apiEventsTotal = useMemo(() => {
    if (live) return liveApiEventsData?.total ?? apiEvents.length;
    return windowApiEventsData?.pages[0]?.total ?? 0;
  }, [apiEvents.length, live, liveApiEventsData?.total, windowApiEventsData?.pages]);

  const jobWorkerOptions = useMemo(() => {
    const workers = new Set<string>();
    for (const worker of workersData?.workers ?? []) {
      for (const instance of worker.instances ?? []) {
        if (instance.id) workers.add(instance.id);
      }
    }
    for (const job of jobs) {
      if (job.worker_id) workers.add(job.worker_id);
    }
    return [...workers].sort((a, b) => a.localeCompare(b));
  }, [jobs, workersData?.workers]);

  const jobFunctionOptions = useMemo(() => {
    const labelsByKey = new Map<string, string>();
    for (const fn of functionsData?.functions ?? []) {
      labelsByKey.set(fn.key, fn.name);
    }
    for (const job of jobs) {
      if (job.function) {
        labelsByKey.set(job.function, job.function_name || job.function);
      }
    }
    return [...labelsByKey.entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [functionsData?.functions, jobs]);

  const apiNameOptions = useMemo(() => {
    const names = new Set<string>();
    for (const api of apisData?.apis ?? []) {
      names.add(api.name);
    }
    for (const event of apiEvents) {
      names.add(event.api_name);
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [apiEvents, apisData?.apis]);

  const apiRouteOptions = useMemo(() => {
    return [...new Set(apiEvents.map((event) => `${event.method} ${event.path}`))].sort((a, b) =>
      a.localeCompare(b)
    );
  }, [apiEvents]);

  const apiStatusOptions = useMemo(() => {
    return [...new Set(apiEvents.map((event) => String(event.status)))].sort((a, b) =>
      Number(a) - Number(b)
    );
  }, [apiEvents]);

  const apiInstanceOptions = useMemo(() => {
    const set = new Set<string>();
    for (const event of apiEvents) {
      set.add(event.instance_id ?? "__none__");
    }
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [apiEvents]);

  const isJobsLoading = live ? isLiveJobsLoading : isWindowJobsLoading;
  const isApiLoading = live ? isLiveApiLoading : isWindowApiLoading;

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
        <SelectTrigger size="sm" className="h-7 w-[180px] bg-muted border-input text-xs">
          <SelectValue placeholder="Function" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Functions</SelectItem>
          {jobFunctionOptions.map((functionOption) => (
            <SelectItem key={functionOption.value} value={functionOption.value}>
              {functionOption.label}
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
        <SelectTrigger size="sm" className="h-7 w-[190px] bg-muted border-input text-xs">
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
    <Tabs
      value={activeTab}
      onValueChange={setActiveTab}
      className={`${className ?? "h-full min-h-0 flex flex-col"} gap-3`}
    >
      <div className="shrink-0 space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <TabsList variant="line" className="h-8">
            <TabsTrigger value="jobs" className="text-xs">
              {live ? `Jobs (Latest ${LIVE_LIST_LIMIT})` : `Jobs (${jobs.length}/${jobsTotal})`}
            </TabsTrigger>
            <TabsTrigger value="api-requests" className="text-xs">
              {live
                ? `API Events (Latest ${LIVE_LIST_LIMIT})`
                : `API Events (${apiEvents.length}/${apiEventsTotal})`}
            </TabsTrigger>
          </TabsList>
          <div className="min-w-0 lg:flex-1">
            {activeTab === "jobs" ? jobsFilterControls : apiFilterControls}
          </div>
        </div>
      </div>

      <Panel
        className="flex-1 min-h-0 overflow-hidden"
        contentClassName="h-full min-h-0 overflow-hidden p-0"
      >
        <TabsContent value="jobs" className="h-full min-h-0 m-0">
          <JobsTable
            jobs={jobs}
            isLoading={isJobsLoading}
            hasMore={!live && Boolean(jobsHasNextPage)}
            isFetchingMore={!live && isFetchingNextJobsPage}
            onLoadMore={
              live
                ? undefined
                : () => {
                    if (jobsHasNextPage && !isFetchingNextJobsPage) {
                      void fetchNextJobsPage();
                    }
                  }
            }
            onJobClick={onJobClick}
            renderActions={(job) => (
              <div className="inline-flex items-center gap-1">
                {RETRYABLE_STATUSES.has(job.status) ? (
                  <Button
                    size="xs"
                    variant="ghost"
                    disabled={retryMutation.isPending}
                    onClick={() => retryMutation.mutate(job.id)}
                    aria-label={`Retry ${job.id}`}
                    title="Retry"
                  >
                    <RotateCcw className="h-3 w-3" />
                  </Button>
                ) : null}
                {CANCELLABLE_STATUSES.has(job.status) ? (
                  <Button
                    size="xs"
                    variant="ghost"
                    disabled={cancelMutation.isPending}
                    onClick={() => cancelMutation.mutate(job.id)}
                    aria-label={`Cancel ${job.id}`}
                    title="Cancel"
                  >
                    <X className="h-3 w-3" />
                  </Button>
                ) : null}
              </div>
            )}
            className="h-full"
            emptyDescription="No jobs match your current filters."
          />
        </TabsContent>

        <TabsContent value="api-requests" className="h-full min-h-0 m-0">
          <ApiRequestsTable
            events={apiEvents}
            isLoading={isApiLoading}
            hasMore={!live && Boolean(apiHasNextPage)}
            isFetchingMore={!live && isFetchingNextApiEventsPage}
            onLoadMore={
              live
                ? undefined
                : () => {
                    if (apiHasNextPage && !isFetchingNextApiEventsPage) {
                      void fetchNextApiEventsPage();
                    }
                  }
            }
            onApiClick={onApiClick}
            className="h-full"
            emptyDescription="No API events match your current filters."
          />
        </TabsContent>
      </Panel>
    </Tabs>
  );
}
