import { useAnimatedNumber } from "@/hooks/use-animated-number";
import { MetricTile } from "@/components/shared";

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
    <MetricTile
      label={label}
      value={displayValue}
      tone={color ?? "text-foreground"}
      sub={sub}
      valueClassName="text-2xl font-bold"
    />
  );
}
