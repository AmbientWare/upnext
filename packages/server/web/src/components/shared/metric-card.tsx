import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: string | number;
  color?: string;
  className?: string;
}

export function MetricCard({ label, value, color = "text-[#e0e0e0]", className }: MetricCardProps) {
  return (
    <div className={cn("text-center", className)}>
      <div className={cn("mono text-lg font-medium", color)}>{value}</div>
      <div className="text-[9px] text-[#555] uppercase tracking-wider">{label}</div>
    </div>
  );
}
