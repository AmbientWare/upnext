import { useState } from "react";

import { Panel } from "@/components/shared";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DashboardStats } from "@/lib/types";
import { cn, formatDateTime, formatDuration } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface RunbookPanelsProps {
  stats: DashboardStats | undefined;
  isPending?: boolean;
  className?: string;
  failingMinRate: number;
  onFailingMinRateChange: (value: number) => void;
  onFunctionClick?: (key: string) => void;
  onJobClick?: (jobId: string) => void;
}

type RunbookTab = "failing" | "queued" | "stuck";

const FAILURE_RATE_OPTIONS = [
  { value: 0, label: "All" },
  { value: 5, label: ">= 5%" },
  { value: 10, label: ">= 10%" },
  { value: 20, label: ">= 20%" },
  { value: 30, label: ">= 30%" },
  { value: 50, label: ">= 50%" },
];

function EmptyState({ label }: { label: string }) {
  return (
    <div className="h-full min-h-[160px] flex items-center justify-center text-xs text-muted-foreground">
      {label}
    </div>
  );
}

function formatAge(seconds: number): string {
  return formatDuration(Math.max(0, seconds) * 1000);
}

function formatWindowMinutes(minutes: number | undefined): string {
  if (!minutes || minutes <= 0) return "selected window";
  if (minutes === 60) return "last hour";
  if (minutes === 24 * 60) return "last 24h";
  if (minutes % 60 === 0) return `last ${minutes / 60}h`;
  return `last ${minutes}m`;
}

export function RunbookPanels({
  stats,
  isPending = false,
  className,
  failingMinRate,
  onFailingMinRateChange,
  onFunctionClick,
  onJobClick,
}: RunbookPanelsProps) {
  const [activeTab, setActiveTab] = useState<RunbookTab>("failing");
  const failing = stats?.top_failing_functions ?? [];
  const oldest = stats?.oldest_queued_jobs ?? [];
  const stuck = stats?.stuck_active_jobs ?? [];
  const windowLabel = formatWindowMinutes(stats?.runs.window_minutes);

  const failingControls = (
    <div className="flex items-center gap-2">
      <Select
        value={String(failingMinRate)}
        onValueChange={(next) => {
          const parsed = Number(next);
          if (Number.isFinite(parsed)) {
            onFailingMinRateChange(parsed);
          }
        }}
      >
        <SelectTrigger size="sm" className="h-6 w-[96px] text-[10px] gap-1 px-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FAILURE_RATE_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={String(opt.value)}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  return (
    <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as RunbookTab)} className="h-full min-h-0">
      <Panel
        title="Runbook"
        className={cn("h-full min-h-0 flex flex-col overflow-hidden", className)}
        contentClassName="flex-1 min-h-0 overflow-hidden p-0"
        titleCenter={(
          <TabsList variant="line" className="h-8">
            <TabsTrigger value="failing" className="text-xs">Failing ({failing.length})</TabsTrigger>
            <TabsTrigger value="queued" className="text-xs">Queued ({oldest.length})</TabsTrigger>
            <TabsTrigger value="stuck" className="text-xs">Stuck ({stuck.length})</TabsTrigger>
          </TabsList>
        )}
        titleRight={activeTab === "failing" ? failingControls : null}
      >
        <div className="border-b border-border" />

        <TabsContent value="failing" className="h-full min-h-0 m-0">
          {isPending ? (
            <EmptyState label="Loading runbook data..." />
          ) : failing.length === 0 ? (
            <EmptyState label={`No failing functions at >= ${failingMinRate}% in the ${windowLabel}.`} />
          ) : (
            <div className="h-full min-h-0 overflow-auto">
              {failing.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className="w-full text-left px-3 py-2 border-b border-border/60 hover:bg-accent/40 last:border-b-0"
                  onClick={() => onFunctionClick?.(item.key)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="mono text-[11px] text-foreground truncate">{item.name}</span>
                    <span className="mono text-[11px] text-red-400">{item.failure_rate.toFixed(1)}%</span>
                  </div>
                  <div className="mono text-[10px] text-muted-foreground mt-1">
                    {item.failures}/{item.runs} failed
                    {item.last_run_at ? ` • ${formatDateTime(new Date(item.last_run_at))}` : ""}
                  </div>
                </button>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="queued" className="h-full min-h-0 m-0">
          {isPending ? (
            <EmptyState label="Loading runbook data..." />
          ) : oldest.length === 0 ? (
            <EmptyState label="No queued jobs." />
          ) : (
            <div className="h-full min-h-0 overflow-auto">
              {oldest.map((item) => (
                <button
                  key={`${item.source}:${item.id}`}
                  type="button"
                  className="w-full text-left px-3 py-2 border-b border-border/60 hover:bg-accent/40 last:border-b-0"
                  onClick={() => onJobClick?.(item.id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="mono text-[11px] text-foreground truncate">{item.function_name}</span>
                    <span className="mono text-[11px] text-amber-400">{formatAge(item.age_seconds)}</span>
                  </div>
                  <div className="mono text-[10px] text-muted-foreground mt-1">
                    {item.id} • {item.source} • {formatDateTime(new Date(item.queued_at))}
                  </div>
                </button>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="stuck" className="h-full min-h-0 m-0">
          {isPending ? (
            <EmptyState label="Loading runbook data..." />
          ) : stuck.length === 0 ? (
            <EmptyState label="No stuck active jobs." />
          ) : (
            <div className="h-full min-h-0 overflow-auto">
              {stuck.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="w-full text-left px-3 py-2 border-b border-border/60 hover:bg-accent/40 last:border-b-0"
                  onClick={() => onJobClick?.(item.id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="mono text-[11px] text-foreground truncate">{item.function_name}</span>
                    <span className="mono text-[11px] text-red-400">{formatAge(item.age_seconds)}</span>
                  </div>
                  <div className="mono text-[10px] text-muted-foreground mt-1">
                    {item.id}
                    {item.worker_id ? ` • ${item.worker_id}` : ""}
                    {` • ${formatDateTime(new Date(item.started_at))}`}
                  </div>
                </button>
              ))}
            </div>
          )}
        </TabsContent>
      </Panel>
    </Tabs>
  );
}
