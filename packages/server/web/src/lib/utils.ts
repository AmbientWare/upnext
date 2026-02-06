import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import type { JobStatus } from "@/lib/types"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatNumber(num: number): string {
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + "M";
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + "K";
  }
  return num.toString();
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
  return `${Math.floor(ms / 3600000)}h ${Math.floor((ms % 3600000) / 60000)}m`;
}

export function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return `${seconds}s ago`;
}

export type { JobStatus };

export const statusConfig: Record<JobStatus, { bg: string; text: string; dot: string; label: string }> = {
  active: { bg: "bg-blue-500/10", text: "text-blue-400", dot: "bg-blue-500", label: "Active" },
  complete: { bg: "bg-emerald-500/10", text: "text-emerald-400", dot: "bg-emerald-500", label: "Complete" },
  failed: { bg: "bg-red-500/10", text: "text-red-400", dot: "bg-red-500", label: "Failed" },
  retrying: { bg: "bg-orange-500/10", text: "text-orange-400", dot: "bg-orange-500", label: "Retrying" },
};
