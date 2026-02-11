import { useAutoAnimate } from "@formkit/auto-animate/react";
import { useNavigate } from "@tanstack/react-router";
import { Circle } from "lucide-react";
import { cn, formatTimeAgo } from "@/lib/utils";
import type { WorkerInfo } from "@/lib/types";
import { ProgressBar } from "@/components/shared";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function WorkersTable({ workers }: { workers: WorkerInfo[] }) {
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
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Instances</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Functions</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Concurrency</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody ref={bodyRef}>
        {workers.map((worker) => {
          const displayFunctions = Array.from(
            new Set(
              worker.functions.map((fnKey) => {
                const fromWorker = worker.function_names?.[fnKey];
                if (fromWorker) return fromWorker;
                for (const inst of worker.instances) {
                  const display = inst.function_names?.[fnKey];
                  if (display) return display;
                }
                return fnKey;
              })
            )
          );
          return (
          <TableRow
            key={worker.name}
            className="border-border hover:bg-accent cursor-pointer"
            tabIndex={0}
            role="link"
            onClick={() => navigate({ to: "/workers/$name", params: { name: worker.name } })}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                navigate({ to: "/workers/$name", params: { name: worker.name } });
              }
            }}
          >
            <TableCell className="py-2">
              <div className="flex items-center gap-2">
                <Circle className={cn("w-2 h-2 shrink-0", worker.active ? "fill-emerald-400 text-emerald-400" : "fill-muted-foreground/60 text-muted-foreground/60")} />
                <span className="text-[11px] text-foreground">{worker.name}</span>
              </div>
            </TableCell>
            <TableCell className="py-2">
              {worker.instances.length > 0 ? (
                <div className="flex flex-col gap-0.5">
                  {worker.instances.map((inst) => (
                    <div key={inst.id} className="flex items-center gap-1.5">
                      <span className="mono text-[10px] text-muted-foreground">{inst.id}</span>
                      <div className="flex items-center gap-1">
                        <ProgressBar
                          value={inst.active_jobs}
                          max={inst.concurrency}
                          color="auto"
                          className="w-12"
                        />
                        <span className="mono text-[10px] text-muted-foreground">
                          {inst.active_jobs}/{inst.concurrency}
                        </span>
                      </div>
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
            <TableCell className="text-[11px] text-muted-foreground py-2">
              {displayFunctions.length === 0
                ? "—"
                : displayFunctions.length > 3
                ? `${displayFunctions.slice(0, 3).join(", ")} +${displayFunctions.length - 3}`
                : displayFunctions.join(", ")}
            </TableCell>
            <TableCell className="mono text-[11px] text-muted-foreground py-2">
              {worker.concurrency}
            </TableCell>
          </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
