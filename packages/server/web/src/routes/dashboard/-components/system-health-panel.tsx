import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";

interface HealthMetric {
  label: string;
  value: string;
  status: "good" | "warn" | "bad";
}

export interface SystemHealthPanelProps {
  status: "operational" | "degraded" | "down";
  metrics: HealthMetric[];
  className?: string;
}

export function SystemHealthPanel({ status, metrics, className }: SystemHealthPanelProps) {
  const statusDisplay = {
    operational: { label: "OPERATIONAL", color: "text-emerald-400", dot: "bg-emerald-500" },
    degraded: { label: "DEGRADED", color: "text-amber-400", dot: "bg-amber-500" },
    down: { label: "DOWN", color: "text-red-400", dot: "bg-red-500" },
  };

  const s = statusDisplay[status];

  return (
    <Panel title="System Health" className={className}>
      <div className="flex items-center gap-2 mb-3">
        <div className={cn("w-3 h-3 rounded-full animate-pulse", s.dot)} />
        <span className={cn("font-medium", s.color)}>{s.label}</span>
      </div>
      <div className="space-y-2 text-[11px]">
        {metrics.map((metric, i) => (
          <div key={i} className="flex items-center justify-between">
            <span className="text-[#666]">{metric.label}</span>
            <span
              className={cn(
                "mono",
                metric.status === "good"
                  ? "text-emerald-400"
                  : metric.status === "warn"
                    ? "text-amber-400"
                    : "text-red-400"
              )}
            >
              {metric.value}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
