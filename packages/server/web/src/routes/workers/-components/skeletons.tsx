import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function WorkersTableSkeleton() {
  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Instances</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Functions</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Concurrency</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 6 }).map((_, index) => (
          <TableRow key={`worker-skeleton-${index}`} className="border-border">
            <TableCell className="py-2">
              <Skeleton className="h-3 w-28" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-40" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-32" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-10" />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
