import { cn } from '@/lib/utils'
import type { WorkerStatus } from '@/lib/interfaces'

const statusConfig: Record<WorkerStatus, { label: string; dotClass: string }> = {
  healthy: { label: 'Healthy', dotClass: 'bg-green-500' },
  unhealthy: { label: 'Unhealthy', dotClass: 'bg-yellow-500' },
  stopped: { label: 'Stopped', dotClass: 'bg-gray-400' },
}

interface HealthBadgeProps {
  status: WorkerStatus
  showLabel?: boolean
  className?: string
}

export function HealthBadge({ status, showLabel = true, className }: HealthBadgeProps) {
  const config = statusConfig[status] || { label: status, dotClass: 'bg-gray-400' }

  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span className={cn('size-2 rounded-full', config.dotClass)} />
      {showLabel && <span className="text-sm">{config.label}</span>}
    </span>
  )
}
