import { Panel, MetricCard } from "@/components/shared";

interface QuickStat {
  label: string;
  value: string;
  color?: string;
}

export interface QuickStatsProps {
  stats: QuickStat[];
  className?: string;
}

export function QuickStats({ stats, className }: QuickStatsProps) {
  return (
    <Panel title="Quick Stats" className={className} contentClassName="p-3 grid grid-cols-2 gap-3">
      {stats.map((stat, i) => (
        <MetricCard key={i} label={stat.label} value={stat.value} color={stat.color} />
      ))}
    </Panel>
  );
}
