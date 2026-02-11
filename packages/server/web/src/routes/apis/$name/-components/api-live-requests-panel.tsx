import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { DateRange } from "react-day-picker";

import { getApiRequestEvents, queryKeys } from "@/lib/upnext-api";
import {
  Panel,
  ApiRequestsTable,
  LiveWindowControls,
  getTimeWindowBounds,
  LIVE_LIST_LIMIT,
  LIVE_REFRESH_INTERVAL_MS,
  type TimeWindowPreset,
} from "@/components/shared";

interface ApiLiveRequestsPanelProps {
  apiName: string;
  className?: string;
}

export function ApiLiveRequestsPanel({ apiName, className }: ApiLiveRequestsPanelProps) {
  const [live, setLive] = useState(true);
  const [windowPreset, setWindowPreset] = useState<TimeWindowPreset>("custom");
  const [dateRange, setDateRange] = useState<DateRange>();

  const queryParams = {
    api_name: apiName,
    ...(live ? { limit: LIVE_LIST_LIMIT } : {}),
  } as const;

  const queryKey = live
    ? queryKeys.apiRequestEvents(queryParams)
    : (["apis", "events-window", queryParams] as const);

  const { data, isPending } = useQuery({
    queryKey,
    queryFn: () => getApiRequestEvents(queryParams),
    refetchInterval: live ? LIVE_REFRESH_INTERVAL_MS : false,
    staleTime: live ? 0 : Number.POSITIVE_INFINITY,
  });

  const events = useMemo(() => {
    const latest = [...(data?.events ?? [])].sort(
      (a, b) => Date.parse(b.at) - Date.parse(a.at)
    );

    if (live) {
      return latest.slice(0, LIVE_LIST_LIMIT);
    }

    const bounds = getTimeWindowBounds(windowPreset, dateRange);
    if (!bounds) {
      return latest;
    }

    const { from, to } = bounds;
    return latest
      .filter((event) => {
        const at = Date.parse(event.at);
        return Number.isFinite(at) && at >= from.getTime() && at <= to.getTime();
      });
  }, [data?.events, dateRange, live, windowPreset]);

  return (
    <Panel
      title="Live API Requests"
      titleRight={
        <div className="flex items-center gap-2">
          <LiveWindowControls
            live={live}
            onLiveChange={setLive}
            preset={windowPreset}
            onPresetChange={setWindowPreset}
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
          />
          <span className="text-[10px] mono text-muted-foreground">{events.length} events</span>
        </div>
      }
      className={className ?? "flex-1 min-h-[260px] flex flex-col overflow-hidden"}
      contentClassName="flex-1 overflow-hidden p-0"
    >
      <ApiRequestsTable
        events={events}
        isLoading={isPending}
        hideApiName
        className="h-full"
        emptyDescription="Live request events for this API will appear here as traffic arrives."
      />
    </Panel>
  );
}
