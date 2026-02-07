import { useAutoAnimate } from "@formkit/auto-animate/react";
import { Circle } from "lucide-react";
import { cn, formatTimeAgo } from "@/lib/utils";
import type { ApiInfo } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function ApisTable({ apis }: { apis: ApiInfo[] }) {
  const [bodyRef] = useAutoAnimate<HTMLTableSectionElement>({
    duration: 180,
    easing: "ease-out",
  });

  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Instances</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Endpoints</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Requests (24h)</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Avg Latency</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Error Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody ref={bodyRef}>
        {apis.map((api) => (
          <TableRow key={api.name} className="border-border hover:bg-accent">
            <TableCell className="py-2">
              <div className="flex items-center gap-2">
                <Circle className={cn("w-2 h-2 shrink-0", api.active ? "fill-emerald-400 text-emerald-400" : "fill-muted-foreground/60 text-muted-foreground/60")} />
                <span className="text-[11px] text-foreground">{api.name}</span>
              </div>
            </TableCell>
            <TableCell className="py-2">
              {(api.instances ?? []).length > 0 ? (
                <div className="flex flex-col gap-0.5">
                  {(api.instances ?? []).map((inst) => (
                    <div key={inst.id} className="flex items-center gap-1.5">
                      <span className="mono text-[10px] text-muted-foreground">{inst.id}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {inst.host}:{inst.port}
                      </span>
                      <span className="text-[10px] text-muted-foreground/60">
                        {formatTimeAgo(new Date(inst.last_heartbeat))}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="text-[10px] text-muted-foreground/60">{"\u2014"}</span>
              )}
            </TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">
              {api.endpoint_count}
            </TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">
              {api.requests_24h.toLocaleString()}
            </TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">{Math.round(api.avg_latency_ms)}ms</TableCell>
            <TableCell className="mono text-[11px] py-2">
              <span
                className={cn(
                  api.error_rate === 0
                    ? "text-muted-foreground"
                    : api.error_rate < 1
                      ? "text-emerald-400"
                      : api.error_rate < 2
                        ? "text-amber-400"
                        : "text-red-400"
                )}
              >
                {api.error_rate.toFixed(1)}%
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
