import { cn } from "@/lib/utils";

interface LiveIndicatorProps {
  label?: string;
  className?: string;
  size?: "sm" | "md";
}

export function LiveIndicator({ label = "LIVE", className, size = "sm" }: LiveIndicatorProps) {
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <div className={cn(
        "rounded-full bg-emerald-500 animate-pulse",
        size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2"
      )} />
      <span className={cn(
        "text-emerald-400",
        size === "sm" ? "text-[9px]" : "text-sm"
      )}>{label}</span>
    </div>
  );
}
