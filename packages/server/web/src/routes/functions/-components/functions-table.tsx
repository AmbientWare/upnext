import { useNavigate } from "@tanstack/react-router";
import { useAutoAnimate } from "@formkit/auto-animate/react";
import { Circle } from "lucide-react";
import { cn, formatNumber, formatDuration } from "@/lib/utils";
import type { FunctionInfo, FunctionType } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const typeStyles: Record<FunctionType, string> = {
  task: "bg-blue-500/20 text-blue-400",
  cron: "bg-violet-500/20 text-violet-400",
  event: "bg-amber-500/20 text-amber-400",
};

export function FunctionsTable({ functions }: { functions: FunctionInfo[] }) {
  const navigate = useNavigate();
  const [bodyRef] = useAutoAnimate<HTMLTableSectionElement>({
    duration: 180,
    easing: "ease-out",
  });

  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Type</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Workers</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">24H Runs</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Success</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Avg Duration</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Timeout</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Retries</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Schedule/Pattern</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody ref={bodyRef}>
        {functions.map((fn) => (
          <TableRow
            key={fn.key}
            className="border-border hover:bg-accent cursor-pointer"
            onClick={() => navigate({ to: "/functions/$name", params: { name: fn.key } })}
          >
            <TableCell className="py-2">
              <div className="flex items-center gap-2">
                <Circle className={cn("w-2 h-2 shrink-0", fn.active ? "fill-emerald-400 text-emerald-400" : "fill-muted-foreground/60 text-muted-foreground/60")} />
                <span className="mono text-[11px]">{fn.name}</span>
              </div>
            </TableCell>
            <TableCell className="py-2">
              <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", typeStyles[fn.type])}>
                {fn.type.toUpperCase()}
              </span>
            </TableCell>
            <TableCell className="py-2">
              {(fn.workers ?? []).length > 0 ? (
                <div className="flex items-center gap-1 flex-wrap">
                  {(fn.workers ?? []).map((w) => (
                    <span key={w} className="text-[10px] px-1.5 py-0.5 rounded bg-muted border border-input text-muted-foreground">
                      {w}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-[10px] text-muted-foreground/60">{"\u2014"}</span>
              )}
            </TableCell>
            <TableCell className="mono text-[11px] py-2">{formatNumber(fn.runs_24h)}</TableCell>
            <TableCell className="mono text-[11px] py-2">
              <span
                className={cn(
                  fn.success_rate >= 99
                    ? "text-emerald-400"
                    : fn.success_rate >= 95
                      ? "text-amber-400"
                      : "text-red-400"
                )}
              >
                {fn.success_rate.toFixed(1)}%
              </span>
            </TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">{formatDuration(fn.avg_duration_ms)}</TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">{fn.timeout ?? "\u2014"}s</TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">{fn.max_retries ?? "\u2014"}</TableCell>
            <TableCell className="mono text-[10px] text-muted-foreground py-2">{fn.schedule || fn.pattern || "\u2014"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
