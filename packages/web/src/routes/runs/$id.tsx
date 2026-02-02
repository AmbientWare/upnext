import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { JsonViewer } from '@/components/shared/JsonViewer'
import { ArrowLeft } from 'lucide-react'
import { getRun } from '@/lib/server/runs'
import type { Run } from '@/lib/interfaces'

export const Route = createFileRoute('/runs/$id')({
  component: RunDetailPage,
  loader: async ({ params }) => {
    try {
      return await getRun({ data: { id: params.id } })
    } catch {
      return null
    }
  },
})

function RunDetailPage() {
  const { id } = Route.useParams()
  const run = Route.useLoaderData() as Run | null

  if (!run) {
    return (
      <>
        <PageHeader
          title="Run Not Found"
          actions={
            <Button variant="outline" size="sm" asChild>
              <Link to="/runs">
                <ArrowLeft className="mr-2 size-4" />
                Back to Runs
              </Link>
            </Button>
          }
        />
        <div className="p-4">
          <p className="text-muted-foreground">
            Run with ID "{id}" was not found.
          </p>
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={`Run ${id.slice(0, 8)}`}
        description={run.function}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge status={run.status} />
            <Button variant="outline" size="sm" asChild>
              <Link to="/runs">
                <ArrowLeft className="mr-2 size-4" />
                Back
              </Link>
            </Button>
          </div>
        }
      />

      <div className="flex-1 space-y-4 p-4">
        {/* Overview */}
        <Card>
          <CardHeader>
            <CardTitle>Overview</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Function</span>
              <span className="font-medium">{run.function}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Worker</span>
              <span>{run.worker_id || '-'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Attempts</span>
              <span>{run.attempts} / {run.max_retries}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Duration</span>
              <span>{run.duration_ms ? `${(run.duration_ms / 1000).toFixed(2)}s` : '-'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Started</span>
              <span>{run.started_at ? new Date(run.started_at).toLocaleString() : '-'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Completed</span>
              <span>{run.completed_at ? new Date(run.completed_at).toLocaleString() : '-'}</span>
            </div>
          </CardContent>
        </Card>

        {/* Arguments */}
        <Card>
          <CardHeader>
            <CardTitle>Arguments</CardTitle>
          </CardHeader>
          <CardContent>
            <JsonViewer data={run.kwargs} />
          </CardContent>
        </Card>

        {/* Result or Error */}
        {run.status === 'complete' && run.result && (
          <Card>
            <CardHeader>
              <CardTitle>Result</CardTitle>
            </CardHeader>
            <CardContent>
              <JsonViewer data={run.result} />
            </CardContent>
          </Card>
        )}

        {run.status === 'failed' && run.error && (
          <Card>
            <CardHeader>
              <CardTitle className="text-destructive">Error</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-auto rounded bg-destructive/10 p-4 text-sm text-destructive">
                {run.error}
              </pre>
            </CardContent>
          </Card>
        )}

        {/* State History */}
        {run.state_history && run.state_history.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>State History</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {run.state_history.map((transition, i) => (
                  <div key={i} className="flex items-start gap-4">
                    <div className="flex flex-col items-center">
                      <div className="size-2 rounded-full bg-primary" />
                      {i < run.state_history.length - 1 && (
                        <div className="h-8 w-px bg-border" />
                      )}
                    </div>
                    <div className="flex-1 pb-4">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{transition.to_state}</span>
                        <span className="text-xs text-muted-foreground">
                          {new Date(transition.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      {transition.message && (
                        <p className="text-sm text-muted-foreground">{transition.message}</p>
                      )}
                      {transition.worker_id && (
                        <p className="text-xs text-muted-foreground">Worker: {transition.worker_id}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  )
}
