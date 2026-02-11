import { useCallback, useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { getJobArtifacts, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { Artifact, ArtifactListResponse, ArtifactStreamEvent } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import type { TreeJob } from "./timeline-model";

interface JobArtifactsTabProps {
  jobs: TreeJob[];
  selectedJobId: string;
}

type ArtifactScope = "all" | "selected";

function artifactDataToText(data: unknown): string {
  if (typeof data === "string") return data;
  if (typeof data === "number" || typeof data === "boolean") return String(data);
  if (data == null) return "null";
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

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
  const [scope, setScope] = useState<ArtifactScope>("all");
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
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

  const selectedArtifactText = useMemo(
    () => (selectedArtifact ? artifactDataToText(selectedArtifact.data) : ""),
    [selectedArtifact]
  );

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

  const handleDownload = useCallback(() => {
    if (!selectedArtifact) return;

    const text = artifactDataToText(selectedArtifact.data);
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${selectedArtifact.name || `artifact-${selectedArtifact.id}`}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, [selectedArtifact]);

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
            <button
              key={`${artifact.job_id}-${artifact.id}`}
              type="button"
              onClick={() => setSelectedArtifact(artifact)}
              className="w-full px-3 py-2 text-[11px] grid grid-cols-[1fr_auto_auto] gap-3 text-left hover:bg-accent/40 transition-colors"
            >
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
            </button>
          ))}
        </div>
      </ScrollArea>

      <Dialog
        open={Boolean(selectedArtifact)}
        onOpenChange={(open) => {
          if (!open) setSelectedArtifact(null);
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="truncate">{selectedArtifact?.name}</DialogTitle>
            <DialogDescription>
              {selectedArtifact?.type} · Job {selectedArtifact?.job_id.slice(0, 8)} ·{" "}
              {selectedArtifact?.created_at ? new Date(selectedArtifact.created_at).toLocaleString() : ""}
            </DialogDescription>
          </DialogHeader>

          <div className="rounded border border-input bg-muted/30 p-3">
            <div className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">Preview</div>
            <ScrollArea className="h-[320px]">
              <pre className="mono text-[11px] text-foreground whitespace-pre-wrap break-all pr-3">
                {selectedArtifactText || "No artifact data available."}
              </pre>
            </ScrollArea>
          </div>

          <DialogFooter showCloseButton>
            <Button type="button" onClick={handleDownload} disabled={!selectedArtifact}>
              <Download className="h-3.5 w-3.5" />
              Download
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
