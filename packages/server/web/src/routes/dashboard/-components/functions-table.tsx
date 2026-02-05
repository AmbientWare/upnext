import { cn, formatNumber, formatDuration } from "@/lib/utils";
import type { TaskFunction } from "@/lib/mock-data";

interface FunctionsTableProps {
  functions: TaskFunction[];
}

export function FunctionsTable({ functions }: FunctionsTableProps) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#141414]">
        <tr className="text-[10px] text-[#666] uppercase tracking-wider">
          <th className="matrix-cell px-3 py-2 text-left font-medium">Name</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Type</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">24H Runs</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Success</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Avg Duration</th>
          <th className="matrix-cell px-3 py-2 text-left font-medium">Timeout</th>
          <th className="px-3 py-2 text-left font-medium">Schedule</th>
        </tr>
      </thead>
      <tbody>
        {functions.map((fn) => (
          <tr key={fn.name} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
            <td className="matrix-cell px-3 py-2 mono text-[11px]">{fn.name}</td>
            <td className="matrix-cell px-3 py-2">
              <span
                className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded font-medium",
                  fn.type === "task"
                    ? "bg-blue-500/20 text-blue-400"
                    : fn.type === "cron"
                      ? "bg-violet-500/20 text-violet-400"
                      : "bg-amber-500/20 text-amber-400"
                )}
              >
                {fn.type.toUpperCase()}
              </span>
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px]">{formatNumber(fn.runsLast24h)}</td>
            <td className="matrix-cell px-3 py-2 mono text-[11px]">
              <span
                className={cn(
                  fn.successRate >= 99
                    ? "text-emerald-400"
                    : fn.successRate >= 95
                      ? "text-amber-400"
                      : "text-red-400"
                )}
              >
                {fn.successRate}%
              </span>
            </td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">{formatDuration(fn.avgDuration)}</td>
            <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#666]">{fn.timeout}s</td>
            <td className="px-3 py-2 mono text-[10px] text-[#555]">{fn.schedule || fn.eventPattern || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
