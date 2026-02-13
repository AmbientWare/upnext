import { Inbox } from "lucide-react";
import { useEffect, useRef, type UIEvent } from "react";

import type { ApiRequestEvent } from "@/lib/types";
import { cn, formatDateTime, formatTimeAgo } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const methodClass: Record<ApiRequestEvent["method"], string> = {
  GET: "text-emerald-400 border-emerald-400/30 bg-emerald-500/10",
  POST: "text-blue-400 border-blue-400/30 bg-blue-500/10",
  PUT: "text-amber-400 border-amber-400/30 bg-amber-500/10",
  PATCH: "text-purple-400 border-purple-400/30 bg-purple-500/10",
  DELETE: "text-red-400 border-red-400/30 bg-red-500/10",
};

export interface ApiRequestsTableProps {
  events: ApiRequestEvent[];
  isLoading?: boolean;
  hideApiName?: boolean;
  hasMore?: boolean;
  isFetchingMore?: boolean;
  onLoadMore?: () => void;
  className?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  onApiClick?: (apiName: string) => void;
}

const SCROLL_THRESHOLD_PX = 120;

function ApiRequestsTableSkeleton({ hideApiName }: { hideApiName?: boolean }) {
  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          {!hideApiName && (
            <TableHead className="text-[10px] text-muted-foreground font-medium h-8">API</TableHead>
          )}
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Route</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Status</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Latency</TableHead>
          <TableHead className="hidden md:table-cell text-[10px] text-muted-foreground font-medium h-8">Instance</TableHead>
          <TableHead className="hidden sm:table-cell text-[10px] text-muted-foreground font-medium h-8">Sampled</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">At</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 6 }).map((_, index) => (
          <TableRow key={`api-request-event-skeleton-${index}`} className="border-border">
            {!hideApiName && (
              <TableCell className="py-1.5">
                <Skeleton className="h-3 w-20" />
              </TableCell>
            )}
            <TableCell className="py-1.5">
              <Skeleton className="h-4 w-36" />
            </TableCell>
            <TableCell className="py-1.5">
              <Skeleton className="h-3 w-10" />
            </TableCell>
            <TableCell className="py-1.5">
              <Skeleton className="h-3 w-12" />
            </TableCell>
            <TableCell className="hidden md:table-cell py-1.5">
              <Skeleton className="h-3 w-16" />
            </TableCell>
            <TableCell className="hidden sm:table-cell py-1.5">
              <Skeleton className="h-3 w-10" />
            </TableCell>
            <TableCell className="py-1.5">
              <Skeleton className="h-3 w-14" />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function statusClass(status: number): string {
  if (status >= 500) return "text-red-400";
  if (status >= 400) return "text-amber-400";
  if (status >= 300) return "text-blue-400";
  return "text-emerald-400";
}

export function ApiRequestsTable({
  events,
  isLoading = false,
  hideApiName = false,
  hasMore = false,
  isFetchingMore = false,
  onLoadMore,
  className,
  emptyTitle = "No API requests yet",
  emptyDescription = "Live request events will appear here once traffic arrives.",
  onApiClick,
}: ApiRequestsTableProps) {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRowRef = useRef<HTMLTableRowElement | null>(null);

  const maybeLoadMore = () => {
    if (!onLoadMore || !hasMore || isFetchingMore) return;
    onLoadMore();
  };

  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const target = event.currentTarget;
    const distanceToBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
    if (distanceToBottom <= SCROLL_THRESHOLD_PX) {
      maybeLoadMore();
    }
  };

  useEffect(() => {
    if (!hasMore || !onLoadMore || !loadMoreRowRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries;
        if (entry?.isIntersecting) {
          maybeLoadMore();
        }
      },
      {
        root: scrollContainerRef.current,
        rootMargin: "0px 0px 200px 0px",
        threshold: 0.01,
      }
    );

    observer.observe(loadMoreRowRef.current);
    return () => observer.disconnect();
  }, [hasMore, isFetchingMore, onLoadMore]);

  return (
    <div className={cn("flex flex-col h-full overflow-hidden", className)}>
      {isLoading ? (
        <div className="flex-1 overflow-auto">
          <ApiRequestsTableSkeleton hideApiName={hideApiName} />
        </div>
      ) : events.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
          <div className="rounded-full bg-muted/60 p-2">
            <Inbox className="h-4 w-4" />
          </div>
          <div className="text-sm font-medium">{emptyTitle}</div>
          <div className="text-xs text-muted-foreground/80">{emptyDescription}</div>
        </div>
      ) : (
        <div ref={scrollContainerRef} className="flex-1 overflow-auto" onScroll={handleScroll}>
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
                {!hideApiName && (
                  <TableHead className="text-[10px] text-muted-foreground font-medium h-8">API</TableHead>
                )}
                <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Route</TableHead>
                <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Status</TableHead>
                <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Latency</TableHead>
                <TableHead className="hidden md:table-cell text-[10px] text-muted-foreground font-medium h-8">Instance</TableHead>
                <TableHead className="hidden sm:table-cell text-[10px] text-muted-foreground font-medium h-8">Sampled</TableHead>
                <TableHead className="text-[10px] text-muted-foreground font-medium h-8">At</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => {
                const onApiClickHandler = onApiClick;
                const clickable = Boolean(onApiClickHandler && event.api_name);
                const handleClick =
                  clickable && event.api_name && onApiClickHandler
                    ? () => onApiClickHandler(event.api_name)
                    : undefined;

                return (
                  <TableRow
                    key={event.id}
                    className={cn("border-border hover:bg-accent", clickable && "cursor-pointer")}
                    onClick={handleClick}
                  >
                    {!hideApiName && (
                      <TableCell className="py-1.5 text-[11px] text-foreground">{event.api_name}</TableCell>
                    )}
                    <TableCell className="py-1.5">
                      <div className="inline-flex items-center gap-2 min-w-0">
                        <span className={cn("px-1.5 py-0.5 rounded border mono text-[10px]", methodClass[event.method])}>
                          {event.method}
                        </span>
                        <span className="mono text-[11px] text-foreground truncate">{event.path}</span>
                      </div>
                    </TableCell>
                    <TableCell className={cn("mono text-[11px] py-1.5", statusClass(event.status))}>{event.status}</TableCell>
                    <TableCell className="mono text-[11px] text-muted-foreground py-1.5">
                      {Math.round(event.latency_ms)}ms
                    </TableCell>
                    <TableCell className="hidden md:table-cell mono text-[11px] text-muted-foreground py-1.5">
                      {event.instance_id ?? "\u2014"}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell mono text-[11px] text-muted-foreground py-1.5">
                      {event.sampled ? "yes" : "no"}
                    </TableCell>
                    <TableCell className="text-[11px] text-muted-foreground py-1.5">
                      <div className="flex flex-col">
                        <span className="mono text-[11px] text-muted-foreground">
                          {formatDateTime(new Date(event.at))}
                        </span>
                        <span className="text-[10px] text-muted-foreground/70">
                          {formatTimeAgo(new Date(event.at))}
                        </span>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {(isFetchingMore || hasMore) ? (
                <TableRow ref={loadMoreRowRef} className="border-border hover:bg-transparent">
                  <TableCell
                    colSpan={hideApiName ? 6 : 7}
                    className="py-2 text-center text-[11px] text-muted-foreground"
                  >
                    {isFetchingMore ? "Loading more..." : "Scroll to load more"}
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
