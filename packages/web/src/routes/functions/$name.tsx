import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft } from 'lucide-react'
import { getFunction } from '@/lib/server/functions'
import type { FunctionDetailResponse } from '@/lib/interfaces'

export const Route = createFileRoute('/functions/$name')({
  component: FunctionDetailPage,
  loader: async ({ params }) => {
    try {
      return await getFunction({ data: { name: params.name } })
    } catch {
      return null
    }
  },
})

function FunctionDetailPage() {
  const { name } = Route.useParams()
  const fn = Route.useLoaderData() as FunctionDetailResponse | null

  if (!fn) {
    return (
      <>
        <PageHeader
          title="Function Not Found"
          actions={
            <Button variant="outline" size="sm" asChild>
              <Link to="/functions">
                <ArrowLeft className="mr-2 size-4" />
                Back to Functions
              </Link>
            </Button>
          }
        />
        <div className="p-4">
          <p className="text-muted-foreground">
            Function "{name}" was not found.
          </p>
        </div>
      </>
    )
  }

  const typeLabel = {
    task: 'Task',
    cron: 'Cron',
    trigger: 'Trigger',
  }[fn.type]

  return (
    <>
      <PageHeader
        title={fn.name}
        actions={
          <div className="flex items-center gap-2">
            <Badge>{typeLabel}</Badge>
            <Button variant="outline" size="sm" asChild>
              <Link to="/functions">
                <ArrowLeft className="mr-2 size-4" />
                Back
              </Link>
            </Button>
          </div>
        }
      />

      <div className="flex-1 space-y-4 p-4">
        {/* Configuration */}
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Timeout</span>
              <span>{fn.timeout}s</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Max Retries</span>
              <span>{fn.max_retries}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Retry Delay</span>
              <span>{fn.retry_delay}s</span>
            </div>
            {fn.schedule && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Schedule</span>
                <span className="font-mono">{fn.schedule}</span>
              </div>
            )}
            {fn.pattern && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Event Pattern</span>
                <span className="font-mono">{fn.pattern}</span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Stats */}
        <Card>
          <CardHeader>
            <CardTitle>Stats (24h)</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Total Runs</span>
              <span>{fn.runs_24h}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Success Rate</span>
              <span>{fn.success_rate.toFixed(1)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Avg Duration</span>
              <span>{fn.avg_duration_ms ? `${(fn.avg_duration_ms / 1000).toFixed(2)}s` : '-'}</span>
            </div>
            {fn.p95_duration_ms && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">p95 Duration</span>
                <span>{(fn.p95_duration_ms / 1000).toFixed(2)}s</span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Runs placeholder */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Runs</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              No recent runs for this function.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
