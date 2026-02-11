import { FolderTree } from "lucide-react";

import type { ApiEndpoint } from "@/lib/types";
import { Panel } from "@/components/shared";
import { cn } from "@/lib/utils";

export type RouteNode = {
  segment: string;
  fullPath: string;
  children: RouteNode[];
  routes: ApiEndpoint[];
  requests_24h: number;
};

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

interface RouteTreePanelProps {
  totalEndpoints: number;
  routeTree: RouteNode[];
}

export function RouteTreePanel({ totalEndpoints, routeTree }: RouteTreePanelProps) {
  return (
    <Panel
      title="Route Tree"
      titleRight={<span className="text-[10px] mono text-muted-foreground">{totalEndpoints} routes</span>}
      noPadding
      className="overflow-hidden"
    >
      {totalEndpoints === 0 ? (
        <div className="p-6 text-sm text-muted-foreground">No tracked routes for this API yet.</div>
      ) : (
        <div className="max-h-[420px] overflow-auto">
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
            {routeTree.map((node) => (
              <TreeNodeRows key={node.fullPath} node={node} depth={0} />
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
