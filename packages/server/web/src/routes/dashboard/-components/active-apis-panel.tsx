import { cn } from "@/lib/utils";
import { Panel } from "@/components/shared";

// Transformed API type for display
interface DisplayApi {
  name: string;
  endpointCount: number;
  requestsPerMin: number;
  avgLatencyMs: number;
  errorRate: number;
}

interface ActiveApisPanelProps {
  apis: DisplayApi[];
  className?: string;
}

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
            <tr key={api.name} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
              <td className="matrix-cell px-3 py-2">
                <span className="mono text-[11px] text-[#999]">{api.name}</span>
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">
                {api.requestsPerMin.toLocaleString()}
              </td>
              <td className="matrix-cell px-3 py-2 mono text-[11px] text-[#888]">
                {Math.round(api.avgLatencyMs)}ms
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
