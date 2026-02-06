import { cn } from "@/lib/utils";

interface ProgressBarProps {
  value: number;
  max?: number;
  showLabel?: boolean;
  size?: "sm" | "md";
  color?: "default" | "success" | "warning" | "danger" | "auto";
  className?: string;
}

export function ProgressBar({
  value,
  max = 100,
  showLabel = false,
  size = "sm",
  color = "default",
  className,
}: ProgressBarProps) {
  const percentage = Math.min((value / max) * 100, 100);

  const getColorClass = () => {
    if (color === "auto") {
      if (percentage > 80) return "bg-red-500";
      if (percentage > 60) return "bg-amber-500";
      return "bg-emerald-500";
    }
    const colors = {
      default: "bg-blue-500",
      success: "bg-emerald-500",
      warning: "bg-amber-500",
      danger: "bg-red-500",
    };
    return colors[color];
  };

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className={cn("flex-1 bg-muted rounded overflow-hidden", size === "sm" ? "h-1.5" : "h-2")}>
        <div className={cn("h-full rounded transition-all", getColorClass())} style={{ width: `${percentage}%` }} />
      </div>
      {showLabel && <span className="mono text-[10px] text-muted-foreground">{percentage.toFixed(0)}%</span>}
    </div>
  );
}
