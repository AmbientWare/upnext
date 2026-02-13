import { useAnimatedNumber } from "@/hooks/use-animated-number";
import { cn } from "@/lib/utils";

interface MetricPillProps {
  label: string;
  value: string;
  tone?: string;
  animate?: boolean;
}

export function MetricPill({ label, value, tone, animate = true }: MetricPillProps) {
  const animatedValue = useAnimatedNumber(value);
  const displayValue = animate ? animatedValue : value;

  return (
    <div className="flex items-center gap-1.5 rounded border border-input bg-muted/15 px-2 py-1">
      <span className={cn("mono text-[13px] font-medium leading-none", tone ?? "text-foreground")}>
        {displayValue}
      </span>
      <span className="text-[9px] text-muted-foreground/70 uppercase tracking-wider leading-none">
        {label}
      </span>
    </div>
  );
}
