import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSecrets, queryKeys } from "@/lib/upnext-api";
import { Button } from "@/components/ui/button";
import { Plus, Search } from "lucide-react";
import { SecretsTable } from "./-components/secrets-table";
import { SecretFormDialog } from "./-components/secret-form-dialog";
import { DeleteSecretDialog } from "./-components/delete-secret-dialog";

export const Route = createFileRoute("/secrets/")({
  component: SecretsPage,
});

function SecretsPage() {
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editSecretId, setEditSecretId] = useState<string | null>(null);
  const [deleteSecretId, setDeleteSecretId] = useState<string | null>(null);

  const { data, isPending } = useQuery({
    queryKey: queryKeys.secrets,
    queryFn: getSecrets,
  });

  const secrets = data?.secrets ?? [];
  const filteredSecrets = search.trim()
    ? secrets.filter((s) =>
        s.name.toLowerCase().includes(search.trim().toLowerCase())
      )
    : secrets;

  return (
    <div className="p-4 h-full flex flex-col overflow-hidden">
      <div className="h-full flex flex-col gap-4">
        <div className="shrink-0 flex items-center gap-2">
          <div className="relative w-full sm:max-w-80">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search secrets..."
              className="w-full bg-muted border border-input rounded-md pl-9 pr-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-ring"
            />
          </div>
          <div className="ml-auto">
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="w-4 h-4 mr-1" />
              Create Secret
            </Button>
          </div>
        </div>

        <div className="matrix-panel rounded flex-1 overflow-auto">
          {isPending ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            </div>
          ) : (
            <SecretsTable
              secrets={filteredSecrets}
              hasSearch={!!search.trim()}
              onEdit={setEditSecretId}
              onDelete={setDeleteSecretId}
            />
          )}
        </div>

        <SecretFormDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
        />
        <SecretFormDialog
          open={editSecretId !== null}
          onOpenChange={(open) => !open && setEditSecretId(null)}
          secretId={editSecretId ?? undefined}
        />
        <DeleteSecretDialog
          secretId={deleteSecretId}
          secretName={secrets.find((s) => s.id === deleteSecretId)?.name}
          onClose={() => setDeleteSecretId(null)}
        />
      </div>
    </div>
  );
}
