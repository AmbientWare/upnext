import { Skeleton } from "@/components/ui/skeleton";
import { Panel } from "@/components/shared";

export function SystemOverviewSkeleton() {
  return (
    <Panel title="System Overview" className="shrink-0" contentClassName="p-5">
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={`overview-skeleton-${index}`} className="flex flex-col gap-2">
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function QueueStatsSkeleton() {
  return (
    <Panel title="Job Queue" className="h-full" contentClassName="h-full p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3 w-24" />
        </div>
        <div className="space-y-2 text-right">
          <Skeleton className="h-3 w-16 ml-auto" />
          <Skeleton className="h-2 w-20 ml-auto" />
        </div>
      </div>
      <div className="space-y-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    </Panel>
  );
}
