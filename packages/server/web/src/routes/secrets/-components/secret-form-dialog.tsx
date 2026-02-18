import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  getSecret,
  createSecret,
  updateSecret,
  queryKeys,
} from "@/lib/upnext-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Eye, EyeOff, Plus, X } from "lucide-react";

type SecretPair = { key: string; value: string };

function defaultPairs(): SecretPair[] {
  return [{ key: "", value: "" }];
}

function pairsFromSecretData(secretData: { data: Record<string, string> } | undefined): SecretPair[] {
  if (!secretData) {
    return defaultPairs();
  }
  const entries = Object.entries(secretData.data);
  if (entries.length === 0) {
    return defaultPairs();
  }
  return entries.map(([key, value]) => ({ key, value }));
}

function clonePairs(pairs: SecretPair[]): SecretPair[] {
  return pairs.map((pair) => ({ ...pair }));
}

export function SecretFormDialog({
  open,
  onOpenChange,
  secretId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  secretId?: string;
}) {
  const queryClient = useQueryClient();
  const isEdit = !!secretId;

  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const [pairsDraft, setPairsDraft] = useState<SecretPair[] | null>(null);
  const [visibleValues, setVisibleValues] = useState<Set<number>>(new Set());

  // Load existing secret data for edit mode
  const { data: secretData } = useQuery({
    queryKey: queryKeys.secret(secretId ?? ""),
    queryFn: () => getSecret(secretId!),
    enabled: isEdit && open,
  });

  const pairs = pairsDraft ?? pairsFromSecretData(secretData);
  const name = nameDraft ?? (isEdit ? secretData?.name ?? "" : "");

  const invalidateSecrets = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.secrets });
    if (secretId) {
      queryClient.invalidateQueries({ queryKey: queryKeys.secret(secretId) });
    }
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const dataObj: Record<string, string> = {};
      for (const p of pairs) {
        if (p.key.trim()) dataObj[p.key.trim()] = p.value;
      }
      return createSecret({ name: name.trim(), data: dataObj });
    },
    onSuccess: () => {
      invalidateSecrets();
      toast.success("Secret created");
      handleClose();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to create secret");
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      const dataObj: Record<string, string> = {};
      for (const p of pairs) {
        if (p.key.trim()) dataObj[p.key.trim()] = p.value;
      }
      return updateSecret(secretId!, { name: name.trim(), data: dataObj });
    },
    onSuccess: () => {
      invalidateSecrets();
      toast.success("Secret updated");
      handleClose();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to update secret");
    },
  });

  const handleClose = () => {
    setNameDraft(null);
    setPairsDraft(null);
    setVisibleValues(new Set());
    onOpenChange(false);
  };

  const addPair = () => setPairsDraft([...clonePairs(pairs), { key: "", value: "" }]);

  const removePair = (index: number) => {
    const next = pairs.filter((_, i) => i !== index);
    setPairsDraft(next.length === 0 ? defaultPairs() : clonePairs(next));
    setVisibleValues((prev) => {
      const next = new Set(prev);
      next.delete(index);
      return next;
    });
  };

  const updatePair = (index: number, field: "key" | "value", val: string) => {
    const next = clonePairs(pairs);
    next[index] = { ...next[index], [field]: val };
    setPairsDraft(next);
  };

  const toggleValueVisibility = (index: number) => {
    setVisibleValues((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const hasValidPairs = pairs.some((p) => p.key.trim() !== "");
  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Secret" : "Create Secret"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update the secret name or key-value pairs."
              : "Define a named secret with key-value pairs. Values are encrypted at rest."}
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (isEdit) updateMutation.mutate();
            else createMutation.mutate();
          }}
          className="space-y-4"
        >
          <div className="space-y-2">
            <label className="text-sm font-medium">Name</label>
            <Input
              value={name}
              onChange={(e) => setNameDraft(e.target.value)}
              placeholder="db-credentials"
              autoFocus={!isEdit}
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Key-Value Pairs</label>
            <div className="space-y-2 max-h-60 overflow-auto">
              {pairs.map((pair, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    value={pair.key}
                    onChange={(e) => updatePair(i, "key", e.target.value)}
                    placeholder="KEY"
                    className="font-mono text-xs flex-1"
                  />
                  <div className="relative flex-1">
                    <Input
                      type={visibleValues.has(i) ? "text" : "password"}
                      value={pair.value}
                      onChange={(e) => updatePair(i, "value", e.target.value)}
                      placeholder="value"
                      className="font-mono text-xs pr-8"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="absolute right-0 top-0 h-full w-8"
                      onClick={() => toggleValueVisibility(i)}
                    >
                      {visibleValues.has(i) ? (
                        <EyeOff className="h-3.5 w-3.5" />
                      ) : (
                        <Eye className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => removePair(i)}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addPair}
              className="w-full"
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              Add Pair
            </Button>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!name.trim() || !hasValidPairs || isPending}
            >
              {isPending
                ? isEdit
                  ? "Saving..."
                  : "Creating..."
                : isEdit
                  ? "Save"
                  : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
