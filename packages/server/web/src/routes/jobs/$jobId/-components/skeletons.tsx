import { Panel } from "@/components/shared";
import { Skeleton } from "@/components/ui/skeleton";

export function JobDetailSkeleton() {
  return (
    <div className="p-4 h-full flex flex-col gap-3 overflow-hidden">
      <div className="space-y-2 shrink-0">
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-6 w-80" />
        <Skeleton className="h-3 w-96" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(340px,380px)] gap-3 min-h-0 flex-1">
        <div className="min-h-0 flex flex-col gap-3">
          <Panel title="Execution Timeline" className="h-[360px]" contentClassName="p-3">
            <Skeleton className="h-full w-full" />
          </Panel>
          <Panel title="Task Runs" className="flex-1 min-h-[260px]" contentClassName="p-3">
            <Skeleton className="h-full w-full" />
          </Panel>
        </div>

        <Panel title="Job Details" className="h-full" contentClassName="p-3">
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        </Panel>
      </div>
    </div>
  );
}
