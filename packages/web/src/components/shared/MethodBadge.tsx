import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { HttpMethod } from '@/lib/interfaces'

const methodConfig: Record<HttpMethod, { className: string }> = {
  GET: { className: 'bg-green-500/10 text-green-600 border-green-500/20' },
  POST: { className: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
  PUT: { className: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20' },
  PATCH: { className: 'bg-purple-500/10 text-purple-600 border-purple-500/20' },
  DELETE: { className: 'bg-red-500/10 text-red-600 border-red-500/20' },
}

interface MethodBadgeProps {
  method: HttpMethod
  className?: string
}

export function MethodBadge({ method, className }: MethodBadgeProps) {
  const config = methodConfig[method] || { className: '' }

  return (
    <Badge variant="outline" className={cn('font-mono', config.className, className)}>
      {method}
    </Badge>
  )
}
