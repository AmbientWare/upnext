import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Copy, Check, ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

interface JsonViewerProps {
  data: unknown
  collapsed?: boolean
  className?: string
}

export function JsonViewer({ data, collapsed = false, className }: JsonViewerProps) {
  const [copied, setCopied] = useState(false)
  const [isCollapsed, setIsCollapsed] = useState(collapsed)

  const jsonString = JSON.stringify(data, null, 2)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(jsonString)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (data === null || data === undefined) {
    return (
      <pre className={cn('rounded bg-muted p-4 text-sm text-muted-foreground', className)}>
        null
      </pre>
    )
  }

  const isExpandable = typeof data === 'object' && data !== null

  return (
    <div className={cn('relative', className)}>
      <div className="absolute right-2 top-2 flex gap-1">
        {isExpandable && (
          <Button
            variant="ghost"
            size="sm"
            className="size-7 p-0"
            onClick={() => setIsCollapsed(!isCollapsed)}
          >
            {isCollapsed ? (
              <ChevronRight className="size-4" />
            ) : (
              <ChevronDown className="size-4" />
            )}
          </Button>
        )}
        <Button variant="ghost" size="sm" className="size-7 p-0" onClick={handleCopy}>
          {copied ? (
            <Check className="size-4 text-green-500" />
          ) : (
            <Copy className="size-4" />
          )}
        </Button>
      </div>
      <pre className="overflow-auto rounded bg-muted p-4 pr-16 text-sm">
        {isCollapsed ? (
          <span className="text-muted-foreground">
            {Array.isArray(data) ? `Array(${data.length})` : `Object(${Object.keys(data as object).length})`}
          </span>
        ) : (
          <code>
            {jsonString.split('\n').map((line, i) => (
              <span key={i} className="block">
                <JsonLine line={line} />
              </span>
            ))}
          </code>
        )}
      </pre>
    </div>
  )
}

function JsonLine({ line }: { line: string }) {
  // Simple syntax highlighting
  const highlighted = line
    // Strings (property values)
    .replace(
      /("(?:[^"\\]|\\.)*")(?=\s*[:,\]]|$)/g,
      '<span class="text-green-600 dark:text-green-400">$1</span>',
    )
    // Numbers
    .replace(
      /\b(\d+\.?\d*)\b/g,
      '<span class="text-blue-600 dark:text-blue-400">$1</span>',
    )
    // Booleans and null
    .replace(
      /\b(true|false|null)\b/g,
      '<span class="text-purple-600 dark:text-purple-400">$1</span>',
    )

  return <span dangerouslySetInnerHTML={{ __html: highlighted }} />
}
