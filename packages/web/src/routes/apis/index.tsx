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
import { MethodBadge } from '@/components/shared/MethodBadge'
import { RelativeTime } from '@/components/shared/RelativeTime'
import { RefreshCw } from 'lucide-react'
import { getApiEndpoints } from '@/lib/server/apis'

export const Route = createFileRoute('/apis/')({
  component: ApisPage,
  loader: async () => {
    try {
      return await getApiEndpoints()
    } catch {
      return { endpoints: [], total: 0 }
    }
  },
})

function ApisPage() {
  const router = useRouter()
  const data = Route.useLoaderData()
  const endpoints = data.endpoints

  return (
    <>
      <PageHeader
        title="API Endpoints"
        description="HTTP endpoints and their stats"
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
                <TableHead className="w-[100px]">Method</TableHead>
                <TableHead>Path</TableHead>
                <TableHead>Requests (24h)</TableHead>
                <TableHead>Avg Latency</TableHead>
                <TableHead>Error Rate</TableHead>
                <TableHead>Last Request</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {endpoints.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    No API endpoints registered. Define some @api routes to see them here.
                  </TableCell>
                </TableRow>
              ) : (
                endpoints.map((endpoint) => (
                  <TableRow key={`${endpoint.method}-${endpoint.path}`}>
                    <TableCell>
                      <MethodBadge method={endpoint.method} />
                    </TableCell>
                    <TableCell>
                      <Link
                        to="/apis/$method/$"
                        params={{ method: endpoint.method, _splat: endpoint.path.slice(1) }}
                        className="font-mono text-sm text-primary hover:underline"
                      >
                        {endpoint.path}
                      </Link>
                    </TableCell>
                    <TableCell>{endpoint.requests_24h.toLocaleString()}</TableCell>
                    <TableCell>{endpoint.avg_latency_ms}ms</TableCell>
                    <TableCell>
                      <ErrorRateBadge rate={endpoint.error_rate} />
                    </TableCell>
                    <TableCell>
                      <RelativeTime date={endpoint.last_request_at} />
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

function ErrorRateBadge({ rate }: { rate: number }) {
  if (rate === 0) {
    return <span className="text-green-500">0%</span>
  }
  if (rate < 1) {
    return <span className="text-yellow-500">{rate.toFixed(2)}%</span>
  }
  return <span className="text-red-500">{rate.toFixed(2)}%</span>
}
