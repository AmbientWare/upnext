import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  getAdminUsers,
  getAdminUserApiKeys,
  createAdminUser,
  deleteAdminUser,
  updateAdminUser,
  rotateAdminApiKey,
  queryKeys,
} from "@/lib/upnext-api";
import type { AdminUser, AdminApiKey } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Copy,
  KeyRound,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  ShieldOff,
  Trash2,
} from "lucide-react";

export const Route = createFileRoute("/admin/")({
  component: AdminPage,
});

function AdminPage() {
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [deleteUserId, setDeleteUserId] = useState<string | null>(null);
  const [apiKeyUserId, setApiKeyUserId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const { data, isPending } = useQuery({
    queryKey: queryKeys.adminUsers,
    queryFn: getAdminUsers,
  });

  const users = data?.users ?? [];
  const filteredUsers = search.trim()
    ? users.filter((u) =>
        u.username.toLowerCase().includes(search.trim().toLowerCase())
      )
    : users;

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      <div className="shrink-0 flex items-center gap-2">
        <div className="relative w-full sm:max-w-80">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search users..."
            className="w-full bg-muted border border-input rounded-md pl-9 pr-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-ring"
          />
        </div>
        <div className="ml-auto">
          <Button size="sm" onClick={() => setCreateUserOpen(true)}>
            <Plus className="w-4 h-4 mr-1" />
            Create User
          </Button>
        </div>
      </div>

      <div className="matrix-panel rounded flex-1 overflow-auto">
        {isPending ? (
          <div className="flex items-center justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          </div>
        ) : filteredUsers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <p className="text-sm">{search.trim() ? "No matching users" : "No users yet"}</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Username</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredUsers.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  onDelete={() => setDeleteUserId(user.id)}
                  onShowApiKey={() => setApiKeyUserId(user.id)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <CreateUserDialog
        open={createUserOpen}
        onOpenChange={setCreateUserOpen}
      />
      <DeleteUserDialog
        userId={deleteUserId}
        username={users.find((u) => u.id === deleteUserId)?.username}
        onClose={() => setDeleteUserId(null)}
      />
      <ApiKeyDialog
        userId={apiKeyUserId}
        username={users.find((u) => u.id === apiKeyUserId)?.username}
        onClose={() => setApiKeyUserId(null)}
      />
    </div>
  );
}

// =============================================================================
// User Row
// =============================================================================

function UserRow({
  user,
  onDelete,
  onShowApiKey,
}: {
  user: AdminUser;
  onDelete: () => void;
  onShowApiKey: () => void;
}) {
  const queryClient = useQueryClient();

  const toggleAdmin = useMutation({
    mutationFn: () =>
      updateAdminUser(user.id, { is_admin: !user.is_admin }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
      toast.success(
        user.is_admin ? "Removed admin role" : "Granted admin role"
      );
    },
  });

  return (
    <TableRow>
      <TableCell className="font-medium">{user.username}</TableCell>
      <TableCell>
        {user.is_admin ? (
          <Badge variant="default">Admin</Badge>
        ) : (
          <Badge variant="secondary">User</Badge>
        )}
      </TableCell>
      <TableCell className="text-muted-foreground text-xs">
        {new Date(user.created_at).toLocaleDateString()}
      </TableCell>
      <TableCell>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <MoreHorizontal className="w-4 h-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onShowApiKey}>
              <KeyRound className="mr-2 h-4 w-4" />
              Show API Key
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => toggleAdmin.mutate()}>
              {user.is_admin ? (
                <>
                  <ShieldOff className="mr-2 h-4 w-4" />
                  Remove Admin
                </>
              ) : (
                <>
                  <ShieldCheck className="mr-2 h-4 w-4" />
                  Make Admin
                </>
              )}
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={onDelete}
              className="text-destructive focus:text-destructive"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete User
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  );
}

// =============================================================================
// Create User Dialog
// =============================================================================

function CreateUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [createdRawKey, setCreatedRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      createAdminUser({ username: username.trim(), is_admin: isAdmin }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
      setCreatedRawKey(data.api_key.raw_key);
    },
  });

  const handleCopy = async () => {
    if (!createdRawKey) return;
    await navigator.clipboard.writeText(createdRawKey);
    setCopied(true);
    toast.success("API key copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const handleClose = () => {
    setUsername("");
    setIsAdmin(false);
    setCreatedRawKey(null);
    setCopied(false);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {createdRawKey ? "User Created" : "Create User"}
          </DialogTitle>
          <DialogDescription>
            {createdRawKey
              ? "Copy this API key now and send it to the user. You won't be able to see it again."
              : "Add a new user. An initial API key will be generated automatically."}
          </DialogDescription>
        </DialogHeader>

        {createdRawKey ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Input
                value={createdRawKey}
                readOnly
                className="font-mono text-xs"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={handleCopy}
                className="shrink-0"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
            {copied && (
              <p className="text-xs text-emerald-500">Copied!</p>
            )}
            <DialogFooter>
              <Button onClick={handleClose}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (username.trim()) mutation.mutate();
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <label className="text-sm font-medium">Username</label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="username"
                autoFocus
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="is-admin"
                checked={isAdmin}
                onCheckedChange={(checked) => setIsAdmin(checked === true)}
              />
              <label htmlFor="is-admin" className="text-sm">
                Admin privileges
              </label>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!username.trim() || mutation.isPending}
              >
                {mutation.isPending ? "Creating..." : "Create"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

// =============================================================================
// Delete User Dialog
// =============================================================================

function DeleteUserDialog({
  userId,
  username,
  onClose,
}: {
  userId: string | null;
  username: string | undefined;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => deleteAdminUser(userId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
      toast.success(`User "${username}" deleted`);
      onClose();
    },
  });

  return (
    <Dialog open={userId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete User</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete <strong>{username}</strong>? This
            will also revoke their API key. This action cannot be undone.
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

// =============================================================================
// API Key Dialog (Show + Rotate)
// =============================================================================

function ApiKeyDialog({
  userId,
  username,
  onClose,
}: {
  userId: string | null;
  username: string | undefined;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [rotatedRawKey, setRotatedRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const { data, isPending } = useQuery({
    queryKey: queryKeys.adminUserApiKeys(userId ?? ""),
    queryFn: () => getAdminUserApiKeys(userId!),
    enabled: userId !== null,
  });

  const currentKey: AdminApiKey | undefined = data?.api_keys?.[0];

  const rotateMutation = useMutation({
    mutationFn: () => rotateAdminApiKey(userId!),
    onSuccess: (result) => {
      setRotatedRawKey(result.raw_key);
      queryClient.invalidateQueries({
        queryKey: queryKeys.adminUserApiKeys(userId!),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers });
      toast.success("API key rotated");
    },
  });

  const handleCopy = async () => {
    if (!rotatedRawKey) return;
    await navigator.clipboard.writeText(rotatedRawKey);
    setCopied(true);
    toast.success("API key copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  const handleClose = () => {
    setRotatedRawKey(null);
    setCopied(false);
    onClose();
  };

  return (
    <Dialog
      open={userId !== null}
      onOpenChange={(open) => !open && handleClose()}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {rotatedRawKey ? "API Key Rotated" : `API Key — ${username}`}
          </DialogTitle>
          <DialogDescription>
            {rotatedRawKey
              ? "Copy this new API key now. You won't be able to see it again."
              : "Rotating will revoke the current key and generate a new one."}
          </DialogDescription>
        </DialogHeader>

        {rotatedRawKey ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Input
                value={rotatedRawKey}
                readOnly
                className="font-mono text-xs"
              />
              <Button
                variant="outline"
                size="icon"
                onClick={handleCopy}
                className="shrink-0"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
            {copied && (
              <p className="text-xs text-emerald-500">Copied!</p>
            )}
            <DialogFooter>
              <Button onClick={handleClose}>Done</Button>
            </DialogFooter>
          </div>
        ) : isPending ? (
          <div className="flex items-center justify-center py-6">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          </div>
        ) : (
          <div className="space-y-4">
            {currentKey ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <span className="text-muted-foreground">Prefix</span>
                  <span className="font-mono">{currentKey.key_prefix}...</span>
                  <span className="text-muted-foreground">Status</span>
                  <span>
                    {currentKey.is_active ? (
                      <Badge variant="default">Active</Badge>
                    ) : (
                      <Badge variant="destructive">Disabled</Badge>
                    )}
                  </span>
                  <span className="text-muted-foreground">Last Used</span>
                  <span>
                    {currentKey.last_used_at
                      ? new Date(currentKey.last_used_at).toLocaleString()
                      : "Never"}
                  </span>
                  <span className="text-muted-foreground">Created</span>
                  <span>
                    {new Date(currentKey.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No API key found for this user.
              </p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={handleClose}>
                Close
              </Button>
              <Button
                variant="destructive"
                onClick={() => rotateMutation.mutate()}
                disabled={rotateMutation.isPending}
              >
                <RefreshCw className="mr-2 h-4 w-4" />
                {rotateMutation.isPending ? "Rotating..." : "Rotate Key"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
