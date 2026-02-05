import { cn, formatNumber, formatTimeAgo } from "@/lib/utils";
import { ProgressBar } from "@/components/shared";
import type { Worker } from "@/lib/mock-data";

interface WorkersTableProps {
  workers: Worker[];
}

export function WorkersTable({ workers }: WorkersTableProps) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">Node</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Status</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Load</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Processed</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Failed</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Functions</th>
          <th className="px-3 py-2 text-left font-medium">Heartbeat</th>
        </tr>
      </thead>
      <tbody>
        {workers.map((worker) => (
          <tr key={worker.id} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
            <td className="matrix-cell px-3 py-2 mono text-[11px]">{worker.name}</td>
            <td className="matrix-cell px-3 py-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-[10px] font-medium",
                  worker.status === "healthy"
                    ? "text-emerald-400"
                    : worker.status === "unhealthy"
                      ? "text-red-400"
                      : "text-[#666]"
                )}
              >
                <div
                  className={cn(
                    "w-1.5 h-1.5 rounded-full",
                    worker.status === "healthy"
                      ? "bg-emerald-500"
                      : worker.status === "unhealthy"
                        ? "bg-red-500"
                        : "bg-[#666]"
                  )}
                />
                {worker.status.toUpperCase()}
              </span>
            </td>
            <td className="matrix-cell px-3 py-2">
              <div className="flex items-center gap-2">
                <ProgressBar
                  value={worker.activeJobs}
                  max={worker.concurrency}
                  color="auto"
                  className="w-16"
                />
                <span className="mono text-[10px] text-[#666]">
                  {worker.activeJobs}/{worker.concurrency}
                </span>
              </div>
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-emerald-400">
              {formatNumber(worker.jobsProcessed)}
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-red-400">{worker.jobsFailed}</td>
            <td className="matrix-cell px-3 py-2 text-[11px] text-[#666]">{worker.functions.length}</td>
            <td className="px-3 py-2 text-[11px] text-[#666]">{formatTimeAgo(worker.lastHeartbeat)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
