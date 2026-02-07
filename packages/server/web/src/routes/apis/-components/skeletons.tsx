import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function ApisTableSkeleton() {
  return (
    <Table>
      <TableHeader className="sticky top-0 z-10 bg-card">
        <TableRow className="text-[10px] text-muted-foreground uppercase tracking-wider border-input hover:bg-transparent">
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Name</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Instances</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Endpoints</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Requests (24h)</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Avg Latency</TableHead>
          <TableHead className="text-[10px] text-muted-foreground font-medium h-8">Error Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 6 }).map((_, index) => (
          <TableRow key={`api-skeleton-${index}`} className="border-border">
            <TableCell className="py-2">
              <Skeleton className="h-3 w-28" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-40" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-12" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-20" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-16" />
            </TableCell>
            <TableCell className="py-2">
              <Skeleton className="h-3 w-14" />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
