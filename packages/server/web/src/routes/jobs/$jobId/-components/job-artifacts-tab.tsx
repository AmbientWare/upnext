import { useCallback, useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Download,
  FileArchive,
  FileCode2,
  FileJson2,
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  type LucideIcon,
} from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { getArtifactContentUrl, getJobArtifacts, queryKeys } from "@/lib/upnext-api";
import { env } from "@/lib/env";
import { useEventSource } from "@/hooks/use-event-source";
import type { Artifact, ArtifactListResponse, ArtifactStreamEvent } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
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
import { cn } from "@/lib/utils";
import type { TreeJob } from "./timeline-model";

interface JobArtifactsTabProps {
  jobs: TreeJob[];
  selectedJobId: string;
}

type ArtifactScope = "all" | "selected";

type ArtifactKind = "image" | "json" | "text" | "table" | "markup" | "pdf" | "binary";

const artifactKindMeta: Record<
  ArtifactKind,
  {
    label: string;
    icon: LucideIcon;
    className: string;
  }
> = {
  image: {
    label: "Image",
    icon: ImageIcon,
    className: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  },
  json: {
    label: "JSON",
    icon: FileJson2,
    className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  text: {
    label: "Text",
    icon: FileText,
    className: "border-zinc-400/40 bg-zinc-500/10 text-zinc-700 dark:text-zinc-200",
  },
  table: {
    label: "CSV",
    icon: FileSpreadsheet,
    className: "border-lime-500/30 bg-lime-500/10 text-lime-700 dark:text-lime-300",
  },
  markup: {
    label: "Markup",
    icon: FileCode2,
    className: "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  },
  pdf: {
    label: "PDF",
    icon: FileArchive,
    className: "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
  },
  binary: {
    label: "Binary",
    icon: FileArchive,
    className: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
};

const artifactStatusMeta: Record<
  string,
  {
    label: string;
    icon: LucideIcon;
    className: string;
  }
> = {
  available: {
    label: "Available",
    icon: CheckCircle2,
    className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  queued: {
    label: "Queued",
    icon: Clock3,
    className: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  error: {
    label: "Error",
    icon: AlertCircle,
    className: "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
  },
};

const fallbackArtifactStatusMeta = {
  label: "Unknown",
  icon: AlertCircle,
  className: "border-zinc-400/40 bg-zinc-500/10 text-zinc-700 dark:text-zinc-200",
};

function getArtifactKind(artifact: Artifact): ArtifactKind {
  const contentType = (artifact.content_type ?? "").toLowerCase();
  const type = (artifact.type ?? "").toLowerCase();

  if (contentType.startsWith("image/") || type.startsWith("image/")) return "image";
  if (contentType.includes("json") || type === "json") return "json";
  if (contentType === "application/pdf" || type === "file/pdf") return "pdf";
  if (contentType.includes("csv") || type === "file/csv") return "table";
  if (
    contentType.includes("xml") ||
    contentType.includes("html") ||
    contentType.includes("svg") ||
    type === "file/xml" ||
    type === "file/html" ||
    type === "image/svg"
  ) {
    return "markup";
  }
  if (contentType.startsWith("text/") || type === "text") return "text";
  return "binary";
}

function getPreviewLanguage(artifact: Artifact): string {
  const contentType = (artifact.content_type ?? "").toLowerCase();
  const type = (artifact.type ?? "").toLowerCase();
  if (contentType.includes("json") || type === "json") return "json";
  if (contentType.includes("xml") || type === "file/xml") return "xml";
  if (contentType.includes("html") || type === "file/html") return "html";
  if (contentType.includes("svg") || type === "image/svg") return "html";
  if (contentType.includes("csv") || type === "file/csv") return "csv";
  return "text";
}

function formatArtifactText(raw: string, language: string): string {
  if (language !== "json") return raw;
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
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

  const selectedArtifactContentUrl = selectedArtifact
    ? getArtifactContentUrl(selectedArtifact.id)
    : null;

  const selectedArtifactDownloadUrl = selectedArtifact
    ? getArtifactContentUrl(selectedArtifact.id, { download: true })
    : null;

  const selectedArtifactContentType = selectedArtifact?.content_type ?? selectedArtifact?.type ?? "";
  const selectedArtifactKind = selectedArtifact ? getArtifactKind(selectedArtifact) : null;
  const selectedArtifactStatusMeta = selectedArtifact
    ? artifactStatusMeta[selectedArtifact.status] ?? fallbackArtifactStatusMeta
    : null;
  const SelectedStatusIcon = selectedArtifactStatusMeta?.icon;
  const isImagePreview = selectedArtifactContentType.startsWith("image/");
  const isPdfPreview = selectedArtifactContentType === "application/pdf" || selectedArtifact?.type === "file/pdf";
  const isTextPreview =
    selectedArtifactContentType.startsWith("text/") ||
    selectedArtifactContentType.includes("json") ||
    selectedArtifactContentType.includes("xml") ||
    selectedArtifactContentType.includes("html");

  const {
    data: selectedArtifactTextPreview,
    isPending: isTextPreviewLoading,
  } = useQuery({
    queryKey: ["artifact", "content-preview", selectedArtifact?.id],
    queryFn: async () => {
      if (!selectedArtifactContentUrl) return "";
      const response = await fetch(selectedArtifactContentUrl);
      if (!response.ok) {
        throw new Error(`Failed to load artifact content (${response.status})`);
      }
      return response.text();
    },
    enabled: Boolean(selectedArtifact && selectedArtifactContentUrl && isTextPreview),
  });
  const selectedArtifactLanguage = selectedArtifact ? getPreviewLanguage(selectedArtifact) : "text";
  const formattedArtifactPreview = useMemo(
    () =>
      selectedArtifactTextPreview
        ? formatArtifactText(selectedArtifactTextPreview, selectedArtifactLanguage)
        : "",
    [selectedArtifactLanguage, selectedArtifactTextPreview]
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
    if (!selectedArtifactDownloadUrl || !selectedArtifact) return;
    const link = document.createElement("a");
    link.href = selectedArtifactDownloadUrl;
    link.rel = "noreferrer";
    link.download = selectedArtifact.name || `artifact-${selectedArtifact.id}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, [selectedArtifact, selectedArtifactDownloadUrl]);

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
          {artifacts.map((artifact) => {
            const kind = getArtifactKind(artifact);
            const kindMeta = artifactKindMeta[kind];
            const statusMeta = artifactStatusMeta[artifact.status] ?? fallbackArtifactStatusMeta;
            const KindIcon = kindMeta.icon;
            const StatusIcon = statusMeta.icon;

            return (
              <button
                key={`${artifact.job_id}-${artifact.id}`}
                type="button"
                onClick={() => setSelectedArtifact(artifact)}
                className="w-full px-3 py-2 text-[11px] grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 text-left hover:bg-accent/40 transition-colors"
              >
                <div className="min-w-0">
                  <div className="mono truncate text-foreground flex items-center gap-2">
                    <KindIcon className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="truncate">{artifact.name}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                    <Badge variant="outline" className={cn("mono text-[10px]", kindMeta.className)}>
                      {kindMeta.label}
                    </Badge>
                    <Badge variant="outline" className={cn("mono text-[10px]", statusMeta.className)}>
                      <StatusIcon className="h-3 w-3" />
                      {statusMeta.label}
                    </Badge>
                    {scope === "all" ? (
                      <span className="mono text-[10px] text-muted-foreground">
                        Job {artifact.job_id.slice(0, 8)}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="mono text-muted-foreground">
                  {formatBytes(artifact.size_bytes)}
                </div>
                <div className="mono text-muted-foreground">
                  {new Date(artifact.created_at).toLocaleTimeString()}
                </div>
              </button>
            );
          })}
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
              Job {selectedArtifact?.job_id.slice(0, 8)} ·{" "}
              {selectedArtifact?.created_at ? new Date(selectedArtifact.created_at).toLocaleString() : ""}
            </DialogDescription>
            {selectedArtifact ? (
              <div className="flex flex-wrap items-center gap-2 pt-2">
                <Badge
                  variant="outline"
                  className={cn(
                    "mono text-[10px]",
                    artifactKindMeta[selectedArtifactKind ?? "binary"].className
                  )}
                >
                  {artifactKindMeta[selectedArtifactKind ?? "binary"].label}
                </Badge>
                {selectedArtifactStatusMeta ? (
                  <Badge
                    variant="outline"
                    className={cn("mono text-[10px]", selectedArtifactStatusMeta.className)}
                  >
                    {SelectedStatusIcon ? <SelectedStatusIcon className="h-3 w-3" /> : null}
                    {selectedArtifactStatusMeta.label}
                  </Badge>
                ) : null}
                {selectedArtifact.content_type ? (
                  <Badge variant="outline" className="mono text-[10px] text-muted-foreground">
                    {selectedArtifact.content_type}
                  </Badge>
                ) : null}
                <Badge variant="outline" className="mono text-[10px] text-muted-foreground">
                  {formatBytes(selectedArtifact.size_bytes)}
                </Badge>
              </div>
            ) : null}
          </DialogHeader>

          <div className="rounded border border-input bg-muted/30 p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Preview</div>
              {isTextPreview && selectedArtifact ? (
                <Badge variant="outline" className="mono text-[10px] text-muted-foreground">
                  {selectedArtifactLanguage}
                </Badge>
              ) : null}
            </div>
            {isImagePreview && selectedArtifactContentUrl ? (
              <div className="h-[320px] overflow-auto">
                <img
                  src={selectedArtifactContentUrl}
                  alt={selectedArtifact?.name ?? "Artifact preview"}
                  className="max-h-full max-w-full object-contain"
                />
              </div>
            ) : isPdfPreview && selectedArtifactContentUrl ? (
              <iframe
                title={selectedArtifact?.name ?? "Artifact preview"}
                src={selectedArtifactContentUrl}
                className="h-[320px] w-full rounded border border-input bg-background"
              />
            ) : isTextPreview ? (
              <ScrollArea className="h-[320px]">
                {isTextPreviewLoading ? (
                  <pre className="mono text-[11px] text-foreground whitespace-pre-wrap break-all pr-3">
                    Loading preview...
                  </pre>
                ) : (
                  <SyntaxHighlighter
                    language={selectedArtifactLanguage}
                    style={vscDarkPlus}
                    customStyle={{
                      margin: 0,
                      background: "transparent",
                      fontSize: "11px",
                      lineHeight: "1.55",
                      padding: 0,
                    }}
                    wrapLongLines
                  >
                    {formattedArtifactPreview || "No artifact content available."}
                  </SyntaxHighlighter>
                )}
              </ScrollArea>
            ) : (
              <div className="h-[320px] flex items-center justify-center text-xs text-muted-foreground">
                Preview unavailable for this artifact type.
              </div>
            )}
          </div>

          <DialogFooter showCloseButton>
            <Button type="button" onClick={handleDownload} disabled={!selectedArtifactDownloadUrl}>
              <Download className="h-3.5 w-3.5" />
              Download
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
