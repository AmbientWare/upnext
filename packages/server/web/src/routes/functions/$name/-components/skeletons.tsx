import { Skeleton } from "@/components/ui/skeleton";
import { Panel } from "@/components/shared";

export function FunctionDetailSkeleton() {
  return (
    <div className="p-4 flex flex-col gap-3 h-full overflow-auto xl:overflow-hidden">
      {/* Header */}
      <div className="shrink-0 space-y-1.5">
        <Skeleton className="h-4 w-20" />
        <div className="flex items-center gap-2.5">
          <Skeleton className="h-2.5 w-2.5 rounded-full" />
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-12 rounded" />
          <Skeleton className="h-6 w-16 rounded" />
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={`metric-pill-${i}`} className="h-7 w-24 rounded" />
          ))}
        </div>
      </div>

      {/* Config + Trends */}
      <div className="shrink-0 grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)] items-stretch gap-3">
        <Panel
          title="Configuration"
          contentClassName="px-3 py-2.5"
        >
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={`config-skel-${i}`}>
                <Skeleton className="h-3 w-16 mb-1" />
                <Skeleton className="h-4 w-12" />
              </div>
            ))}
          </div>
          <div className="mt-2.5 pt-2.5 border-t border-input/60">
            <Skeleton className="h-3 w-14 mb-1.5" />
            <div className="flex gap-1">
              <Skeleton className="h-5 w-20 rounded" />
              <Skeleton className="h-5 w-16 rounded" />
            </div>
          </div>
        </Panel>

        <Panel
          title="Job Trends"
          className="h-56 xl:h-full flex flex-col overflow-hidden"
          contentClassName="flex-1 p-3"
        >
          <Skeleton className="h-full w-full" />
        </Panel>
      </div>

      {/* Jobs table */}
      <Panel
        title="Recent Jobs"
        className="flex-1 min-h-0 flex flex-col overflow-hidden"
        contentClassName="flex-1 p-3"
      >
        <div className="flex flex-col gap-2">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={`job-skel-${i}`} className="h-4 w-full" />
          ))}
        </div>
      </Panel>
    </div>
  );
}
