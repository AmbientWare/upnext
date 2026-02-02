import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { RunStatus } from '@/lib/interfaces'

const statusConfig: Record<
  RunStatus,
  { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline'; className?: string }
> = {
  pending: { label: 'Pending', variant: 'secondary' },
  queued: { label: 'Queued', variant: 'outline', className: 'border-blue-500 text-blue-500' },
  active: { label: 'Active', variant: 'outline', className: 'border-amber-500 text-amber-500 animate-pulse' },
  complete: { label: 'Complete', variant: 'outline', className: 'border-green-500 text-green-500' },
  failed: { label: 'Failed', variant: 'destructive' },
  cancelled: { label: 'Cancelled', variant: 'secondary', className: 'line-through' },
  retrying: { label: 'Retrying', variant: 'outline', className: 'border-orange-500 text-orange-500' },
}

interface StatusBadgeProps {
  status: RunStatus
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = statusConfig[status] || { label: status, variant: 'secondary' as const }

  return (
    <Badge
      variant={config.variant}
      className={cn(config.className, className)}
    >
      {config.label}
    </Badge>
  )
}
