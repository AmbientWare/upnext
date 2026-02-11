import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface MetricTileProps {
  label: string;
  value: ReactNode;
  tone?: string;
  sub?: ReactNode;
  className?: string;
  valueClassName?: string;
}

export function MetricTile({
  label,
  value,
  tone = "text-foreground",
  sub,
  className,
  valueClassName,
}: MetricTileProps) {
  return (
    <div className={cn("rounded border border-input bg-muted/20 px-3 py-2 min-h-[62px]", className)}>
      <div className={cn("mono text-xl leading-tight", tone, valueClassName)}>{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-1">{label}</div>
      {sub ? <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div> : null}
    </div>
  );
}
