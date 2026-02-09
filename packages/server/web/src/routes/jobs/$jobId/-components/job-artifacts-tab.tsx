import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getJobArtifacts, queryKeys } from "@/lib/conduit-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { Artifact, ArtifactListResponse, ArtifactStreamEvent } from "@/lib/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";

interface JobArtifactsTabProps {
  selectedJobId: string;
}

function upsertArtifact(artifacts: Artifact[], nextArtifact: Artifact): Artifact[] {
  const withoutExisting = artifacts.filter((artifact) => artifact.id !== nextArtifact.id);
  const merged = [nextArtifact, ...withoutExisting];
  merged.sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  return merged;
}

export function JobArtifactsTab({ selectedJobId }: JobArtifactsTabProps) {
  const queryClient = useQueryClient();
  const artifactsQueryKey = queryKeys.jobArtifacts(selectedJobId);

  const { data, isPending } = useQuery({
    queryKey: artifactsQueryKey,
    queryFn: () => getJobArtifacts(selectedJobId),
    enabled: Boolean(selectedJobId),
  });

  const streamUrl = `${env.VITE_API_BASE_URL}/jobs/${encodeURIComponent(selectedJobId)}/artifacts/stream`;
  const handleArtifactStreamMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data) return;

      let payload: ArtifactStreamEvent;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }

      if (payload.job_id !== selectedJobId) return;

      queryClient.setQueryData<ArtifactListResponse>(artifactsQueryKey, (old) => {
        const current = old ?? { artifacts: [], total: 0 };

        if (payload.type === "artifact.deleted" && payload.artifact_id != null) {
          const artifacts = current.artifacts.filter(
            (artifact) => artifact.id !== payload.artifact_id
          );
          return { artifacts, total: artifacts.length };
        }

        if (
          (payload.type === "artifact.created" || payload.type === "artifact.promoted") &&
          payload.artifact
        ) {
          const artifacts = upsertArtifact(current.artifacts, payload.artifact);
          return { artifacts, total: artifacts.length };
        }

        return current;
      });
    },
    [artifactsQueryKey, queryClient, selectedJobId]
  );

  useEventSource(streamUrl, {
    enabled: Boolean(selectedJobId),
    onMessage: handleArtifactStreamMessage,
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
