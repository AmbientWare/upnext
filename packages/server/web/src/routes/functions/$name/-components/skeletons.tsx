import { Skeleton } from "@/components/ui/skeleton";
import { Panel } from "@/components/shared";

export function FunctionDetailSkeleton() {
  return (
    <div className="p-4 flex flex-col gap-3 h-full overflow-auto">
      <div className="shrink-0 flex flex-col gap-2">
        <Skeleton className="h-4 w-24" />
        <div className="flex items-center gap-3">
          <Skeleton className="h-3 w-3 rounded-full" />
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>
      </div>

      <div className="flex gap-3 shrink-0">
        <Panel title="Configuration" className="flex-1" contentClassName="p-4">
          <div className="grid grid-cols-2 gap-x-8 gap-y-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={`config-skeleton-${index}`} className="flex items-center gap-2">
                <Skeleton className="h-3 w-3 rounded-full" />
                <Skeleton className="h-3 w-24" />
              </div>
            ))}
            <div className="col-span-2">
              <Skeleton className="h-3 w-32" />
              <div className="flex gap-2 mt-2">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-16" />
              </div>
            </div>
          </div>
        </Panel>

        <Panel title="Metrics (24H)" className="flex-1" contentClassName="p-4">
          <div className="grid grid-cols-3 gap-x-6 gap-y-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={`metric-skeleton-${index}`} className="flex flex-col gap-2">
                <Skeleton className="h-6 w-20" />
                <Skeleton className="h-3 w-24" />
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Job Trends" className="shrink-0 h-56 flex flex-col overflow-hidden" contentClassName="p-3">
        <Skeleton className="h-full w-full" />
      </Panel>

      <Panel title="Recent Jobs" className="flex-1 min-h-64 flex flex-col overflow-hidden" contentClassName="p-3">
        <div className="flex flex-col gap-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={`jobs-skeleton-${index}`} className="h-4 w-full" />
          ))}
        </div>
      </Panel>
    </div>
  );
}
