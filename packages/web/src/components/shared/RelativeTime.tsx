import { useEffect, useState } from 'react'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'

function getRelativeTime(date: Date): string {
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSecs = Math.floor(diffMs / 1000)
  const diffMins = Math.floor(diffSecs / 60)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffSecs < 60) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`

  return date.toLocaleDateString()
}

interface RelativeTimeProps {
  date: string | Date | null
  className?: string
}

export function RelativeTime({ date, className }: RelativeTimeProps) {
  const [relativeTime, setRelativeTime] = useState<string>('')

  useEffect(() => {
    if (!date) return

    const d = typeof date === 'string' ? new Date(date) : date
    setRelativeTime(getRelativeTime(d))

    const interval = setInterval(() => {
      setRelativeTime(getRelativeTime(d))
    }, 60000) // Update every minute

    return () => clearInterval(interval)
  }, [date])

  if (!date) return <span className={className}>-</span>

  const d = typeof date === 'string' ? new Date(date) : date

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={className}>{relativeTime}</span>
      </TooltipTrigger>
      <TooltipContent>
        {d.toLocaleString()}
      </TooltipContent>
    </Tooltip>
  )
}
