import { Skeleton } from "@/components/ui/skeleton";
import { Panel } from "@/components/shared";

export function SystemOverviewSkeleton() {
  return (
    <Panel title="System Overview" className="shrink-0" contentClassName="p-5">
      <div className="grid grid-cols-4 gap-6">
        {Array.from({ length: 7 }).map((_, index) => (
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
