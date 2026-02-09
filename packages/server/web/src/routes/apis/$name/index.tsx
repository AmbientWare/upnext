import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, FolderTree } from "lucide-react";

import { getApi, queryKeys } from "@/lib/conduit-api";
import type { ApiEndpoint } from "@/lib/types";
import { Panel } from "@/components/shared/panel";
import { cn, formatNumber } from "@/lib/utils";

export const Route = createFileRoute("/apis/$name/")({
  component: ApiDetailPage,
});

type RouteNode = {
  segment: string;
  fullPath: string;
  children: RouteNode[];
  routes: ApiEndpoint[];
  requests_24h: number;
};

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

const methodClass: Record<ApiEndpoint["method"], string> = {
  GET: "text-emerald-400 border-emerald-400/30 bg-emerald-500/10",
  POST: "text-blue-400 border-blue-400/30 bg-blue-500/10",
  PUT: "text-amber-400 border-amber-400/30 bg-amber-500/10",
  PATCH: "text-purple-400 border-purple-400/30 bg-purple-500/10",
  DELETE: "text-red-400 border-red-400/30 bg-red-500/10",
};
const routeTreeGridClass = "grid grid-cols-[minmax(260px,1fr)_90px_90px_90px_90px_90px_90px]";

function RouteRow({ endpoint, depth }: { endpoint: ApiEndpoint; depth: number }) {
  return (
    <div
      className={cn(routeTreeGridClass, "items-center px-3 py-1.5 text-[11px] border-t border-border/50")}
    >
      <div className="flex items-center gap-2 min-w-0" style={{ paddingLeft: `${12 + depth * 16}px` }}>
        <span className={cn("px-1.5 py-0.5 rounded border mono text-[10px]", methodClass[endpoint.method])}>
          {endpoint.method}
        </span>
        <span className="mono text-foreground truncate">{endpoint.path}</span>
      </div>
      <span className="mono text-muted-foreground">{endpoint.requests_24h.toLocaleString()}</span>
      <span className="mono text-muted-foreground">{endpoint.requests_per_min.toFixed(1)}</span>
      <span className="mono text-muted-foreground">{Math.round(endpoint.avg_latency_ms)}ms</span>
      <span className="mono text-emerald-400">{endpoint.success_rate.toFixed(1)}%</span>
      <span className="mono text-amber-400">{endpoint.client_error_rate.toFixed(1)}%</span>
      <span className="mono text-red-400">{endpoint.server_error_rate.toFixed(1)}%</span>
    </div>
  );
}

function TreeNodeRows({ node, depth }: { node: RouteNode; depth: number }) {
  return (
    <>
      <div
        className={cn(routeTreeGridClass, "items-center px-3 py-1.5 text-[11px] border-t border-border/40 bg-muted/20")}
      >
        <div className="flex items-center gap-2 min-w-0" style={{ paddingLeft: `${12 + depth * 16}px` }}>
          <FolderTree className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="mono text-muted-foreground truncate">{node.fullPath}</span>
        </div>
        <span className="mono text-muted-foreground">{node.requests_24h.toLocaleString()}</span>
        <span className="mono text-muted-foreground">{"\u2014"}</span>
        <span className="mono text-muted-foreground">{"\u2014"}</span>
        <span className="mono text-muted-foreground">{"\u2014"}</span>
        <span className="mono text-muted-foreground">{"\u2014"}</span>
        <span className="mono text-muted-foreground">{"\u2014"}</span>
      </div>
      {node.routes.map((endpoint) => (
        <RouteRow key={`${endpoint.method}:${endpoint.path}`} endpoint={endpoint} depth={depth + 1} />
      ))}
      {node.children.map((child) => (
        <TreeNodeRows key={child.fullPath} node={child} depth={depth + 1} />
      ))}
    </>
  );
}

function ApiDetailPage() {
  const { name } = Route.useParams();

  const { data, isPending, error } = useQuery({
    queryKey: queryKeys.api(name),
    queryFn: () => getApi(name),
    refetchInterval: 45000,
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

      <Panel
        title="Route Tree"
        titleRight={<span className="text-[10px] mono text-muted-foreground">{data.total_endpoints} routes</span>}
        noPadding
        className="overflow-hidden"
      >
        {data.endpoints.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">No tracked routes for this API yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[820px]">
              <div className={cn(routeTreeGridClass, "px-3 py-2 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border bg-muted/30")}>
                <span>Route</span>
                <span>Req (24h)</span>
                <span>Req / Min</span>
                <span>Latency</span>
                <span>Success</span>
                <span>4xx</span>
                <span>5xx</span>
              </div>
              {tree.map((node) => (
                <TreeNodeRows key={node.fullPath} node={node} depth={0} />
              ))}
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
