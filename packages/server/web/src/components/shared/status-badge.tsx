import { cn, statusConfig, type JobStatus } from "@/lib/utils";
import { StatusIcon } from "./status-icon";

interface StatusBadgeProps {
  status: JobStatus;
  showIcon?: boolean;
  size?: "sm" | "md";
  className?: string;
}

export function StatusBadge({ status, showIcon = true, size = "sm", className }: StatusBadgeProps) {
  const config = statusConfig[status];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 font-medium uppercase tracking-wider",
        size === "sm" ? "text-[10px]" : "text-xs",
        config.text,
        className
      )}
    >
      {showIcon && <StatusIcon status={status} size="sm" />}
      {config.label}
    </span>
  );
}
