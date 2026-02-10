import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { getApi, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { ApiEndpoint, ApiSnapshotEvent } from "@/lib/types";
import { Panel } from "@/components/shared";
import { cn, formatNumber } from "@/lib/utils";

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
    <div className="p-4 h-full overflow-auto flex flex-col gap-4">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-wrap">
          <Link to="/apis" className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
            <ArrowLeft className="w-3.5 h-3.5" />
            Back to APIs
          </Link>
          <span className="text-muted-foreground/60">/</span>
          <h2 className="text-lg font-semibold text-foreground truncate">{api.name}</h2>
          <span className={cn("w-2 h-2 rounded-full", api.active ? "bg-emerald-400" : "bg-muted-foreground/50")} />
        </div>

        {api.docs_url ? (
          <a
            href={api.docs_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex w-fit items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-input text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            Open FastAPI Docs
            <ExternalLink className="w-3 h-3" />
          </a>
        ) : null}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Panel title="Requests (24h)" className="min-h-[74px]">
          <div className="text-lg mono text-foreground">{formatNumber(api.requests_24h)}</div>
        </Panel>
        <Panel title="Req / Min" className="min-h-[74px]">
          <div className="text-lg mono text-foreground">{api.requests_per_min.toFixed(1)}</div>
        </Panel>
        <Panel title="Avg Latency" className="min-h-[74px]">
          <div className="text-lg mono text-foreground">{Math.round(api.avg_latency_ms)}ms</div>
        </Panel>
        <Panel title="Success Rate" className="min-h-[74px]">
          <div className="text-lg mono text-emerald-400">{api.success_rate.toFixed(1)}%</div>
        </Panel>
        <Panel title="Error Rate" className="min-h-[74px]">
          <div className="text-lg mono text-red-400">{api.error_rate.toFixed(1)}%</div>
        </Panel>
        <Panel title="4xx Rate" className="min-h-[74px]">
          <div className="text-lg mono text-amber-400">{api.client_error_rate.toFixed(1)}%</div>
        </Panel>
        <Panel title="5xx Rate" className="min-h-[74px]">
          <div className="text-lg mono text-red-400">{api.server_error_rate.toFixed(1)}%</div>
        </Panel>
        <Panel title="Endpoints / Instances" className="min-h-[74px]">
          <div className="text-lg mono text-foreground">{api.endpoint_count} / {api.instance_count}</div>
        </Panel>
      </div>

      <RouteTreePanel totalEndpoints={data.total_endpoints} routeTree={tree} />

      <ApiLiveRequestsPanel apiName={api.name} />
    </div>
  );
}
