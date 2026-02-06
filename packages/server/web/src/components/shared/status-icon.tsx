import { Loader2, CheckCircle, XCircle, RotateCcw } from "lucide-react";
import { cn, type JobStatus } from "@/lib/utils";

interface StatusIconProps {
  status: JobStatus;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeClasses = {
  sm: "w-3 h-3",
  md: "w-4 h-4",
  lg: "w-5 h-5",
};

const statusColors: Record<JobStatus, string> = {
  active: "text-blue-500",
  complete: "text-emerald-500",
  failed: "text-red-500",
  retrying: "text-orange-500",
};

export function StatusIcon({ status, size = "md", className }: StatusIconProps) {
  const sizeClass = sizeClasses[size];
  const colorClass = statusColors[status];

  const icons: Record<JobStatus, React.ReactNode> = {
    active: <Loader2 className={cn(sizeClass, colorClass, "animate-spin", className)} />,
    complete: <CheckCircle className={cn(sizeClass, colorClass, className)} />,
    failed: <XCircle className={cn(sizeClass, colorClass, className)} />,
    retrying: <RotateCcw className={cn(sizeClass, colorClass, className)} />,
  };

  return <>{icons[status]}</>;
}
