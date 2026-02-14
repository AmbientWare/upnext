import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { deleteSecret, queryKeys } from "@/lib/upnext-api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function DeleteSecretDialog({
  secretId,
  secretName,
  onClose,
}: {
  secretId: string | null;
  secretName: string | undefined;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => deleteSecret(secretId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.secrets });
      toast.success(`Secret "${secretName}" deleted`);
      onClose();
    },
  });

  return (
    <Dialog open={secretId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete Secret</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete <strong>{secretName}</strong>? Any
            workers or APIs referencing this secret will fail on next startup.
            This action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Deleting..." : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
