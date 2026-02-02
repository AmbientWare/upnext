import { createFileRoute, Link, useRouter } from '@tanstack/react-router'
import { useCallback } from 'react'
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
import { StatusBadge } from '@/components/shared/StatusBadge'
import { RelativeTime } from '@/components/shared/RelativeTime'
import { RefreshCw, Pause, Play } from 'lucide-react'
import { getRuns } from '@/lib/server/runs'
import { useAutoRefresh } from '@/hooks/use-auto-refresh'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/runs/')({
  component: RunsPage,
  loader: async () => {
    try {
      return await getRuns()
    } catch {
      return { jobs: [], total: 0, has_more: false }
    }
  },
})

function RunsPage() {
  const router = useRouter()
  const data = Route.useLoaderData()
  const runs = data.jobs

  const refresh = useCallback(() => {
    router.invalidate()
  }, [router])

  const { enabled: autoRefreshEnabled, toggle: toggleAutoRefresh } = useAutoRefresh(refresh, {
    interval: 5000,
    enabled: false,
  })

  return (
    <>
      <PageHeader
        title="Runs"
        description="All job executions"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant={autoRefreshEnabled ? 'default' : 'outline'}
              size="sm"
              onClick={toggleAutoRefresh}
              className={cn(autoRefreshEnabled && 'bg-green-600 hover:bg-green-700')}
            >
              {autoRefreshEnabled ? (
                <>
                  <Pause className="mr-2 size-4" />
                  Auto
                </>
              ) : (
                <>
                  <Play className="mr-2 size-4" />
                  Auto
                </>
              )}
            </Button>
            <Button variant="outline" size="sm" onClick={refresh}>
              <RefreshCw className="mr-2 size-4" />
              Refresh
            </Button>
          </div>
        }
      />

      <div className="flex-1 p-4">
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">ID</TableHead>
                <TableHead>Function</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Worker</TableHead>
                <TableHead>Started</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    No runs found. Execute some tasks to see them here.
                  </TableCell>
                </TableRow>
              ) : (
                runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell className="font-mono text-xs">
                      <Link
                        to="/runs/$id"
                        params={{ id: run.id }}
                        className="text-primary hover:underline"
                      >
                        {run.id.slice(0, 8)}
                      </Link>
                    </TableCell>
                    <TableCell className="font-medium">{run.function}</TableCell>
                    <TableCell>
                      <StatusBadge status={run.status} />
                    </TableCell>
                    <TableCell>
                      {run.duration_ms ? `${(run.duration_ms / 1000).toFixed(2)}s` : '-'}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {run.worker_id || '-'}
                    </TableCell>
                    <TableCell>
                      <RelativeTime date={run.started_at} />
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
