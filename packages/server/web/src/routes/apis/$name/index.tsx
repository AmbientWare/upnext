import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { getApi, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { ApiEndpoint, ApiSnapshotEvent } from "@/lib/types";
import { BackLink, DetailPageLayout, MetricPill, StatusDot, TypeBadge } from "@/components/shared";
import { formatNumber } from "@/lib/utils";

import { ApiLiveRequestsPanel } from "./-components/api-live-requests-panel";
import { RouteTreePanel, type RouteNode } from "./-components/route-tree-panel";

export const Route = createFileRoute("/apis/$name/")({
  component: ApiDetailPage,
});

const SAFETY_RESYNC_MS = 10 * 60 * 1000;

function buildRouteTree(endpoints: ApiEndpoint[]): RouteNode[] {
  type MutableNode = {
    segment: string;
    fullPath: string;
    children: Map<string, MutableNode>;
    routes: ApiEndpoint[];
    requests_24h: number;
  };

  const root: MutableNode = {
    segment: "/",
    fullPath: "/",
    children: new Map(),
    routes: [],
    requests_24h: 0,
  };

  for (const endpoint of endpoints) {
    const segments = endpoint.path.split("/").filter(Boolean);
    let cursor = root;

    for (const segment of segments) {
      const fullPath =
        cursor.fullPath === "/" ? `/${segment}` : `${cursor.fullPath}/${segment}`;
      const existing = cursor.children.get(segment);
      if (existing) {
        cursor = existing;
        continue;
      }
      const next: MutableNode = {
        segment,
        fullPath,
        children: new Map(),
        routes: [],
        requests_24h: 0,
      };
      cursor.children.set(segment, next);
      cursor = next;
    }

    cursor.routes.push(endpoint);
  }

  const finalize = (node: MutableNode): RouteNode => {
    const children = Array.from(node.children.values())
      .map(finalize)
      .sort((a, b) => a.fullPath.localeCompare(b.fullPath));
    const routeRequests = node.routes.reduce((sum, route) => sum + route.requests_24h, 0);
    const childRequests = children.reduce((sum, child) => sum + child.requests_24h, 0);
    return {
      segment: node.segment,
      fullPath: node.fullPath,
      children,
      routes: [...node.routes].sort((a, b) => a.method.localeCompare(b.method)),
      requests_24h: routeRequests + childRequests,
    };
  };

  return Array.from(root.children.values())
    .map(finalize)
    .sort((a, b) => a.fullPath.localeCompare(b.fullPath));
}

function ApiDetailPage() {
  const { name } = Route.useParams();
  const queryClient = useQueryClient();

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.api(name),
    queryFn: () => getApi(name),
    refetchInterval: SAFETY_RESYNC_MS,
  });

  const streamUrl = `${env.VITE_API_BASE_URL}/apis/${encodeURIComponent(name)}/stream`;
  const handleApiStreamMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data) return;

      let payload: ApiSnapshotEvent;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }

      if (payload.type !== "api.snapshot") return;
      queryClient.setQueryData(queryKeys.api(name), payload.api);
    },
    [name, queryClient]
  );

  useEventSource(streamUrl, {
    pauseWhenHidden: true,
    onMessage: handleApiStreamMessage,
  });

  const tree = useMemo(() => buildRouteTree(data?.endpoints ?? []), [data?.endpoints]);

  if (isPending) {
    return <div className="p-4 text-sm text-muted-foreground">Loading API metrics...</div>;
  }

  if (error || !data) {
    return <div className="p-4 text-sm text-red-400">Failed to load API metrics.</div>;
  }

  const api = data.api;

  return (
    <DetailPageLayout>
      {/* ─── Header (compact) ─── */}
      <div className="shrink-0 space-y-1.5">
        <BackLink to="/apis" label="APIs" />

        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5 min-w-0">
            <StatusDot active={api.active} />
            <h2 className="mono text-lg font-semibold text-foreground truncate">{api.name}</h2>
            <TypeBadge label="API" color="emerald" />
            {!api.active && (
              <span className="text-[10px] text-muted-foreground/60 uppercase">Inactive</span>
            )}
            {api.docs_url ? (
              <a
                href={api.docs_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-input text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              >
                Docs
                <ExternalLink className="w-2.5 h-2.5" />
              </a>
            ) : null}
          </div>
        </div>

        {/* Metrics strip */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <MetricPill label="Req 24h" value={formatNumber(api.requests_24h)} />
          <MetricPill label="Req/min" value={api.requests_per_min.toFixed(1)} />
          <MetricPill label="Avg Latency" value={`${Math.round(api.avg_latency_ms)}ms`} />
          <MetricPill
            label="Success"
            value={`${api.success_rate.toFixed(1)}%`}
            tone={
              api.success_rate >= 99
                ? "text-emerald-400"
                : api.success_rate >= 95
                  ? "text-amber-400"
                  : "text-red-400"
            }
          />
          <MetricPill
            label="4xx"
            value={`${api.client_error_rate.toFixed(1)}%`}
            tone={api.client_error_rate > 5 ? "text-amber-400" : undefined}
          />
          <MetricPill
            label="5xx"
            value={`${api.server_error_rate.toFixed(1)}%`}
            tone={api.server_error_rate > 1 ? "text-red-400" : undefined}
          />
          <MetricPill label="Endpoints" value={String(api.endpoint_count)} />
          <MetricPill label="Instances" value={String(api.instance_count)} />
        </div>
      </div>

      {/* ─── Route Tree ─── */}
      <RouteTreePanel
        totalEndpoints={data.total_endpoints}
        routeTree={tree}
        className="shrink-0 max-h-[40%]"
      />

      {/* ─── Live Requests ─── */}
      <ApiLiveRequestsPanel apiName={api.name} className="flex-1 min-h-0 flex flex-col overflow-hidden" />
    </DetailPageLayout>
  );
}
