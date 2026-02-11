import { useCallback, useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { getJobArtifacts, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { Artifact, ArtifactListResponse, ArtifactStreamEvent } from "@/lib/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import type { TreeJob } from "./timeline-model";

interface JobArtifactsTabProps {
  jobs: TreeJob[];
  selectedJobId: string;
}

type ArtifactScope = "all" | "selected";

function upsertArtifact(artifacts: Artifact[], nextArtifact: Artifact): Artifact[] {
  const withoutExisting = artifacts.filter((artifact) => artifact.id !== nextArtifact.id);
  const merged = [nextArtifact, ...withoutExisting];
  merged.sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  return merged;
}

function sortArtifacts(artifacts: Artifact[]): Artifact[] {
  return [...artifacts].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
}

export function JobArtifactsTab({ jobs, selectedJobId }: JobArtifactsTabProps) {
  const queryClient = useQueryClient();
  const [scope, setScope] = useState<ArtifactScope>("selected");
  const jobIds = useMemo(() => jobs.map((job) => job.id), [jobs]);

  const artifactsQueryKey = queryKeys.jobArtifacts(selectedJobId);

  const { data: selectedData, isPending: isSelectedPending } = useQuery({
    queryKey: artifactsQueryKey,
    queryFn: () => getJobArtifacts(selectedJobId),
    enabled: Boolean(selectedJobId),
  });

  const allArtifactsQueries = useQueries({
    queries: jobIds.map((jobId) => ({
      queryKey: queryKeys.jobArtifacts(jobId),
      queryFn: () => getJobArtifacts(jobId),
      enabled: scope === "all",
    })),
  });

  const artifacts = useMemo(() => {
    if (scope === "selected") {
      return sortArtifacts(selectedData?.artifacts ?? []);
    }

    const all = allArtifactsQueries.flatMap((result) => result.data?.artifacts ?? []);
    return sortArtifacts(all);
  }, [allArtifactsQueries, scope, selectedData?.artifacts]);

  const isPending = scope === "selected"
    ? isSelectedPending
    : allArtifactsQueries.some((result) => result.isPending);

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

  if (artifacts.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        {scope === "selected" ? "No artifacts for this task yet." : "No artifacts for this timeline yet."}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="shrink-0 flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setScope("all")}
            className={`text-[10px] px-2 py-1 rounded border ${scope === "all" ? "bg-accent border-input text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            All Tasks
          </button>
          <button
            type="button"
            onClick={() => setScope("selected")}
            className={`text-[10px] px-2 py-1 rounded border ${scope === "selected" ? "bg-accent border-input text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            Selected Task
          </button>
        </div>
        <span className="text-[10px] text-muted-foreground mono">
          {artifacts.length} artifacts
        </span>
      </div>

      <ScrollArea className="h-full">
        <div className="divide-y divide-border">
          {artifacts.map((artifact) => (
            <div key={`${artifact.job_id}-${artifact.id}`} className="px-3 py-2 text-[11px] grid grid-cols-[1fr_auto_auto] gap-3">
              <div className="min-w-0">
                <div className="mono truncate text-foreground">{artifact.name}</div>
                <div className="mono text-muted-foreground">
                  {artifact.type}
                  {scope === "all" ? ` \u00b7 ${artifact.job_id.slice(0, 8)}` : ""}
                </div>
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
    </div>
  );
}
