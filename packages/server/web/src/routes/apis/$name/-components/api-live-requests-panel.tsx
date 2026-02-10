import { useQuery } from "@tanstack/react-query";

import { getApiRequestEvents, queryKeys } from "@/lib/upnext-api";
import { Panel, ApiRequestsTable } from "@/components/shared";

interface ApiLiveRequestsPanelProps {
  apiName: string;
}

const SAFETY_RESYNC_MS = 10 * 60 * 1000;

export function ApiLiveRequestsPanel({ apiName }: ApiLiveRequestsPanelProps) {
  const { data, isPending } = useQuery({
    queryKey: queryKeys.apiRequestEvents({ api_name: apiName, limit: 200 }),
    queryFn: () => getApiRequestEvents({ api_name: apiName, limit: 200 }),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const events = data?.events ?? [];

  return (
    <Panel
      title="Live API Requests"
      titleRight={<span className="text-[10px] mono text-muted-foreground">{events.length} events</span>}
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
