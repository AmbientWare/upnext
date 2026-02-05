import { cn, formatTimeAgo } from "@/lib/utils";
import { Panel, ProgressBar } from "@/components/shared";
import type { Worker } from "@/lib/mock-data";

interface ActiveWorkersPanelProps {
  workers: Worker[];
}

const hostingStyles = {
  managed: "bg-sky-500/20 text-sky-400",
  "self-hosted": "bg-violet-500/20 text-violet-400",
};

export function ActiveWorkersPanel({ workers }: ActiveWorkersPanelProps) {
  return (
    <Panel
      title="Active Workers"
      titleRight={<span className="text-[9px] text-[#555]">{workers.length} nodes</span>}
      contentClassName="overflow-auto"
      className="flex-1 flex flex-col overflow-hidden"
    >
      <table className="w-full">
        <thead className="sticky top-0 bg-[#141414]">
          <tr className="text-[10px] text-[#666] uppercase tracking-wider">
            <th className="matrix-cell px-3 py-2 text-left font-medium">Node</th>
            <th className="matrix-cell px-3 py-2 text-left font-medium">Load</th>
            <th className="matrix-cell px-3 py-2 text-left font-medium">Functions</th>
            <th className="px-3 py-2 text-left font-medium">Heartbeat</th>
          </tr>
        </thead>
        <tbody>
          {workers.map((worker) => (
            <tr key={worker.id} className="matrix-row hover:bg-[#1a1a1a] transition-colors">
              <td className="matrix-cell px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="mono text-[11px]">{worker.name}</span>
                  <span className={cn("text-[8px] px-1 py-0.5 rounded font-medium", hostingStyles[worker.hosting])}>
                    {worker.hosting === "self-hosted" ? "SH" : "M"}
                  </span>
                </div>
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
              <td className="matrix-cell px-3 py-2 text-[11px] text-[#666]">{worker.functions.length}</td>
              <td className="px-3 py-2 text-[11px] text-[#666]">{formatTimeAgo(worker.lastHeartbeat)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
