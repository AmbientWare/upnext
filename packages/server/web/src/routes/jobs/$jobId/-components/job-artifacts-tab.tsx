import { useQuery } from "@tanstack/react-query";
import { getJobArtifacts, queryKeys } from "@/lib/conduit-api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";

interface JobArtifactsTabProps {
  selectedJobId: string;
  refreshMs: number;
}

export function JobArtifactsTab({ selectedJobId, refreshMs }: JobArtifactsTabProps) {
  const { data, isPending } = useQuery({
    queryKey: queryKeys.jobArtifacts(selectedJobId),
    queryFn: () => getJobArtifacts(selectedJobId),
    enabled: Boolean(selectedJobId),
    refetchInterval: refreshMs,
  });

  if (isPending) {
    return (
      <div className="p-3 space-y-2">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
      </div>
    );
  }

  const artifacts = data?.artifacts ?? [];

  if (artifacts.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        No artifacts for this task yet.
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="divide-y divide-border">
        {artifacts.map((artifact) => (
          <div key={artifact.id} className="px-3 py-2 text-[11px] grid grid-cols-[1fr_auto_auto] gap-3">
            <div className="min-w-0">
              <div className="mono truncate text-foreground">{artifact.name}</div>
              <div className="mono text-muted-foreground">{artifact.type}</div>
            </div>
            <div className="mono text-muted-foreground">
              {artifact.size_bytes != null ? `${artifact.size_bytes} B` : "—"}
            </div>
            <div className="mono text-muted-foreground">
              {new Date(artifact.created_at).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
