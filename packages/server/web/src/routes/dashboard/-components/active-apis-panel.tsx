import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";
import type { Api } from "@/lib/mock-data";

interface ActiveApisPanelProps {
  apis: Api[];
  className?: string;
}

const statusColors = {
  healthy: "bg-emerald-500",
  degraded: "bg-amber-500",
  down: "bg-red-500",
};

const hostingStyles = {
  managed: "bg-sky-500/20 text-sky-400",
  "self-hosted": "bg-violet-500/20 text-violet-400",
};

export function ActiveApisPanel({ apis, className }: ActiveApisPanelProps) {
  const totalReqPerMin = apis.reduce((sum, a) => sum + a.requestsPerMin, 0);

  return (
    <Panel
      title="Active APIs"
      titleRight={<span className="text-[9px] text-[#555]">{totalReqPerMin.toLocaleString()} req/min</span>}
      contentClassName="overflow-auto"
      className={cn("flex-1 flex flex-col overflow-hidden", className)}
    >
      <table className="w-full">
        <thead className="sticky top-0 bg-[#141414]">
          <tr className="text-[10px] text-[#666] uppercase tracking-wider">
            <th className="matrix-cell px-3 py-2 text-left font-medium">Name</th>
            <th className="matrix-cell px-3 py-2 text-left font-medium">Req/min</th>
            <th className="matrix-cell px-3 py-2 text-left font-medium">Latency</th>
            <th className="px-3 py-2 text-left font-medium">Errors</th>
          </tr>
        </thead>
        <tbody>
          {apis.map((api) => (
            <tr key={api.id} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
              <td className="matrix-cell px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className={cn("w-2 h-2 rounded-full", statusColors[api.status])} />
                  <span className="mono text-[11px] text-[#999]">{api.name}</span>
                  <span className={cn("text-[8px] px-1 py-0.5 rounded font-medium", hostingStyles[api.hosting])}>
                    {api.hosting === "self-hosted" ? "SH" : "M"}
                  </span>
                </div>
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">
                {api.requestsPerMin.toLocaleString()}
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">
                {api.avgLatencyMs}ms
              </td>
              <td className="px-3 py-2 mono text-[11px]">
                <span
                  className={cn(
                    api.errorRate === 0
                      ? "text-[#555]"
                      : api.errorRate < 1
                        ? "text-emerald-400"
                        : api.errorRate < 2
                          ? "text-amber-400"
                          : "text-red-400"
                  )}
                >
                  {api.errorRate}%
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
