import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { HealthBadge } from '@/components/shared/HealthBadge'
import { ArrowLeft } from 'lucide-react'
import { getWorker } from '@/lib/server/workers'
import type { Worker } from '@/lib/interfaces'

export const Route = createFileRoute('/workers/$id')({
  component: WorkerDetailPage,
  loader: async ({ params }) => {
    try {
      return await getWorker({ data: { id: params.id } })
    } catch {
      return null
    }
  },
})

function WorkerDetailPage() {
  const { id } = Route.useParams()
  const worker = Route.useLoaderData() as Worker | null

  if (!worker) {
    return (
      <>
        <PageHeader
          title="Worker Not Found"
          actions={
            <Button variant="outline" size="sm" asChild>
              <Link to="/workers">
                <ArrowLeft className="mr-2 size-4" />
                Back to Workers
              </Link>
            </Button>
          }
        />
        <div className="p-4">
          <p className="text-muted-foreground">
            Worker with ID "{id}" was not found.
          </p>
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={worker.id}
        actions={
          <div className="flex items-center gap-2">
            <HealthBadge status={worker.status} />
            <Button variant="outline" size="sm" asChild>
              <Link to="/workers">
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
              <span className="text-muted-foreground">Concurrency</span>
              <span>{worker.concurrency}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Active Jobs</span>
              <span>{worker.active_jobs}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Jobs Processed</span>
              <span>{worker.jobs_processed.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Jobs Failed</span>
              <span>{worker.jobs_failed.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Started</span>
              <span>{new Date(worker.started_at).toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Last Heartbeat</span>
              <span>{new Date(worker.last_heartbeat).toLocaleString()}</span>
            </div>
            {worker.hostname && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Hostname</span>
                <span>{worker.hostname}</span>
              </div>
            )}
            {worker.version && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Version</span>
                <span>{worker.version}</span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Functions Handled */}
        <Card>
          <CardHeader>
            <CardTitle>Functions Handled</CardTitle>
          </CardHeader>
          <CardContent>
            {worker.functions.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {worker.functions.map((fn) => (
                  <Badge key={fn} variant="secondary">{fn}</Badge>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">All functions</p>
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
              No recent runs on this worker.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
