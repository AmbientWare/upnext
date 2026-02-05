import { formatDuration, formatTimeAgo } from "@/lib/utils";
import { StatusBadge } from "./status-badge";
import { ProgressBar } from "./progress-bar";
import type { Job } from "@/lib/mock-data";

interface JobsTableProps {
  jobs: Job[];
  onJobClick?: (job: Job) => void;
}

export function JobsTable({ jobs, onJobClick }: JobsTableProps) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">ID</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Function</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Status</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Duration</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Worker</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Age</th>
          <th className="px-3 py-2 text-left font-medium">Progress</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr
            key={job.id}
            onClick={() => onJobClick?.(job)}
            className="matrix-row hover:bg-[#1a1a1a] transition-colors cursor-pointer"
          >
            <td className="matrix-cell px-3 py-1.5 mono text-[11px] text-[#888]">{job.id.slice(0, 12)}</td>
            <td className="matrix-cell px-3 py-1.5 text-[11px]">{job.function}</td>
            <td className="matrix-cell px-3 py-1.5">
              <StatusBadge status={job.status} />
            </td>
            <td className="matrix-cell px-3 py-1.5 mono text-[11px] text-[#888]">
              {job.durationMs ? formatDuration(job.durationMs) : "—"}
            </td>
            <td className="matrix-cell px-3 py-1.5 mono text-[11px] text-[#666]">{job.workerId || "—"}</td>
            <td className="matrix-cell px-3 py-1.5 text-[11px] text-[#666]">{formatTimeAgo(job.scheduledAt)}</td>
            <td className="px-3 py-1.5">
              {job.status === "active" && job.progress !== undefined ? (
                <ProgressBar value={job.progress * 100} showLabel size="sm" />
              ) : (
                <span className="text-[#333]">—</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
