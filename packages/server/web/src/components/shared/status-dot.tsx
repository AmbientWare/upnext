import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusDotProps {
  active: boolean;
  className?: string;
}

export function StatusDot({ active, className }: StatusDotProps) {
  return (
    <Circle
      className={cn(
        "w-2.5 h-2.5 shrink-0",
        active
          ? "fill-emerald-400 text-emerald-400"
          : "fill-muted-foreground/60 text-muted-foreground/60",
        className
      )}
    />
  );
}
