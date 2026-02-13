import { Skeleton } from "@/components/ui/skeleton";
import { Panel } from "@/components/shared";

export function SystemOverviewSkeleton() {
  return (
    <Panel title="System Overview" className="shrink-0" contentClassName="p-5">
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={`overview-skeleton-${index}`} className="flex flex-col gap-2">
            <Skeleton className="h-9 w-24" />
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-4 w-20" />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function QueueStatsSkeleton() {
  return (
    <Panel title="Job Queue" className="h-full" contentClassName="h-full p-5 flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <Skeleton className="h-10 w-20" />
          <Skeleton className="h-4 w-24" />
        </div>
        <div className="space-y-2 text-right">
          <Skeleton className="h-4 w-20 ml-auto" />
          <Skeleton className="h-2 w-24 ml-auto" />
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={`queue-skeleton-${index}`} className="h-10 w-full" />
        ))}
      </div>
      <Skeleton className="h-4 w-36" />
    </Panel>
  );
}
