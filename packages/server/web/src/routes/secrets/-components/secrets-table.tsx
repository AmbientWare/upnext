import type { SecretInfo } from "@/lib/types";
import { Button } from "@/components/ui/button";
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
import { Lock, MoreHorizontal, Pencil, Trash2 } from "lucide-react";

export function SecretsTable({
  secrets,
  hasSearch,
  onEdit,
  onDelete,
}: {
  secrets: SecretInfo[];
  hasSearch: boolean;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (secrets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <Lock className="w-8 h-8 mb-2 opacity-40" />
        <p className="text-sm">{hasSearch ? "No matching secrets" : "No secrets yet"}</p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Keys</TableHead>
          <TableHead>Updated</TableHead>
          <TableHead className="w-12" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {secrets.map((secret) => (
          <SecretRow
            key={secret.id}
            secret={secret}
            onEdit={() => onEdit(secret.id)}
            onDelete={() => onDelete(secret.id)}
          />
        ))}
      </TableBody>
    </Table>
  );
}

function SecretRow({
  secret,
  onEdit,
  onDelete,
}: {
  secret: SecretInfo;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <TableRow>
      <TableCell className="font-medium font-mono text-sm">
        {secret.name}
      </TableCell>
      <TableCell className="text-muted-foreground text-xs">
        {secret.keys.length} {secret.keys.length === 1 ? "key" : "keys"}
      </TableCell>
      <TableCell className="text-muted-foreground text-xs">
        {new Date(secret.updated_at).toLocaleDateString()}
      </TableCell>
      <TableCell>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <MoreHorizontal className="w-4 h-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onEdit}>
              <Pencil className="mr-2 h-4 w-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={onDelete}
              className="text-destructive focus:text-destructive"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  );
}
