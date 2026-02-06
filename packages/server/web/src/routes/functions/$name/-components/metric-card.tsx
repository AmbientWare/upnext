import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string;
  color?: string;
  sub?: string;
}

export function MetricCard({ label, value, color, sub }: MetricCardProps) {
  return (
    <div>
      <div className={cn("mono text-2xl font-bold", color ?? "text-foreground")}>{value}</div>
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">{label}</div>
      {sub && <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}
