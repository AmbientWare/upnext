import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { DateRange } from "react-day-picker";

import { getApiRequestEvents, queryKeys } from "@/lib/upnext-api";
import {
  Panel,
  ApiRequestsTable,
  LiveWindowControls,
  getTimeWindowBounds,
  type TimeWindowPreset,
} from "@/components/shared";

interface ApiLiveRequestsPanelProps {
  apiName: string;
}

const SAFETY_RESYNC_MS = 10 * 60 * 1000;
const LIVE_RESYNC_MS = 5 * 1000;
const DISPLAY_LIMIT = 50;
const WINDOW_QUERY_LIMIT = 500;

export function ApiLiveRequestsPanel({ apiName }: ApiLiveRequestsPanelProps) {
  const [live, setLive] = useState(true);
  const [windowPreset, setWindowPreset] = useState<TimeWindowPreset>("1h");
  const [dateRange, setDateRange] = useState<DateRange>();

  const { data, isPending } = useQuery({
    queryKey: queryKeys.apiRequestEvents({
      api_name: apiName,
      limit: live ? DISPLAY_LIMIT : WINDOW_QUERY_LIMIT,
    }),
    queryFn: () =>
      getApiRequestEvents({
        api_name: apiName,
        limit: live ? DISPLAY_LIMIT : WINDOW_QUERY_LIMIT,
      }),
    refetchInterval: live ? LIVE_RESYNC_MS : false,
    staleTime: live ? 0 : SAFETY_RESYNC_MS,
  });

  const events = useMemo(() => {
    const latest = [...(data?.events ?? [])].sort(
      (a, b) => Date.parse(b.at) - Date.parse(a.at)
    );

    if (live) {
      return latest.slice(0, DISPLAY_LIMIT);
    }

    const bounds = getTimeWindowBounds(windowPreset, dateRange);
    if (!bounds) {
      return latest.slice(0, DISPLAY_LIMIT);
    }

    const { from, to } = bounds;
    return latest
      .filter((event) => {
        const at = Date.parse(event.at);
        return Number.isFinite(at) && at >= from.getTime() && at <= to.getTime();
      })
      .slice(0, DISPLAY_LIMIT);
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
      className="flex-1 min-h-[260px] flex flex-col overflow-hidden"
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
