import { createFileRoute, Link, useRouter } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { HealthBadge } from '@/components/shared/HealthBadge'
import { RelativeTime } from '@/components/shared/RelativeTime'
import { RefreshCw } from 'lucide-react'
import { getWorkers } from '@/lib/server/workers'

export const Route = createFileRoute('/workers/')({
  component: WorkersPage,
  loader: async () => {
    try {
      return await getWorkers()
    } catch {
      return { workers: [], total: 0 }
    }
  },
})

function WorkersPage() {
  const router = useRouter()
  const data = Route.useLoaderData()
  const workers = data.workers

  return (
    <>
      <PageHeader
        title="Workers"
        description="Running worker instances"
        actions={
          <Button variant="outline" size="sm" onClick={() => router.invalidate()}>
            <RefreshCw className="mr-2 size-4" />
            Refresh
          </Button>
        }
      />

      <div className="flex-1 p-4">
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Worker ID</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Uptime</TableHead>
                <TableHead>Active</TableHead>
                <TableHead>Processed</TableHead>
                <TableHead>Last Heartbeat</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    No workers connected. Start a worker to see it here.
                  </TableCell>
                </TableRow>
              ) : (
                workers.map((worker) => (
                  <TableRow key={worker.id}>
                    <TableCell>
                      <Link
                        to="/workers/$id"
                        params={{ id: worker.id }}
                        className="font-mono text-sm text-primary hover:underline"
                      >
                        {worker.id}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <HealthBadge status={worker.status} />
                    </TableCell>
                    <TableCell>
                      <Uptime startedAt={worker.started_at} />
                    </TableCell>
                    <TableCell>
                      {worker.active_jobs}/{worker.concurrency}
                    </TableCell>
                    <TableCell>{worker.jobs_processed.toLocaleString()}</TableCell>
                    <TableCell>
                      <RelativeTime date={worker.last_heartbeat} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </>
  )
}

function Uptime({ startedAt }: { startedAt: string }) {
  const start = new Date(startedAt)
  const now = new Date()
  const diffMs = now.getTime() - start.getTime()

  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

  if (days > 0) return <span>{days}d {hours}h</span>
  if (hours > 0) return <span>{hours}h {minutes}m</span>
  return <span>{minutes}m</span>
}
