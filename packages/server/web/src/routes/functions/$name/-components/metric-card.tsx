import { cn } from "@/lib/utils";
import { useAnimatedNumber } from "@/hooks/use-animated-number";

interface MetricCardProps {
  label: string;
  value: string;
  color?: string;
  sub?: string;
  animate?: boolean;
}

export function MetricCard({ label, value, color, sub, animate = true }: MetricCardProps) {
  const animatedValue = useAnimatedNumber(value);
  const displayValue = animate ? animatedValue : value;

  return (
    <div>
      <div className={cn("mono text-2xl font-bold", color ?? "text-foreground")}>{displayValue}</div>
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">{label}</div>
      {sub && <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}
