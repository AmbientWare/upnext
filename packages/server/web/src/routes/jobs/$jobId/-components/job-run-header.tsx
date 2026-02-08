import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { StatusBadge } from "@/components/shared/status-badge";
import { formatDuration, formatTimeAgo } from "@/lib/utils";
import type { Job } from "@/lib/types";

interface JobRunHeaderProps {
  job: Job;
}

export function JobRunHeader({ job }: JobRunHeaderProps) {
  return (
    <div className="shrink-0 flex flex-col gap-2">
      <Link
        to="/functions/$name"
        params={{ name: job.function }}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
      >
        <ArrowLeft className="w-3 h-3" />
        Back to Function
      </Link>

      <div className="flex items-center gap-3">
        <h2 className="mono text-lg font-semibold text-foreground">
          Job {job.id.slice(0, 12)}
        </h2>
        <StatusBadge status={job.status} />
        <span className="text-xs text-muted-foreground">{job.function_name || job.function}</span>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>Attempts: {job.attempts}/{job.max_retries + 1}</span>
        <span>Worker: {job.worker_id ?? "—"}</span>
        <span>
          Duration: {job.duration_ms ? formatDuration(job.duration_ms) : "—"}
        </span>
        <span>
          Started: {job.started_at ? formatTimeAgo(new Date(job.started_at)) : "—"}
        </span>
      </div>
    </div>
  );
}
