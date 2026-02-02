import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { MethodBadge } from '@/components/shared/MethodBadge'
import { ArrowLeft } from 'lucide-react'
import { getApiEndpoint } from '@/lib/server/apis'
import type { ApiDetailResponse, HttpMethod } from '@/lib/interfaces'

export const Route = createFileRoute('/apis/$method/$')({
  component: ApiDetailPage,
  loader: async ({ params }) => {
    const path = '/' + params._splat
    try {
      return await getApiEndpoint({ data: { method: params.method, path } })
    } catch {
      return null
    }
  },
})

function ApiDetailPage() {
  const { method, _splat } = Route.useParams()
  const path = '/' + _splat
  const endpoint = Route.useLoaderData() as ApiDetailResponse | null

  if (!endpoint) {
    return (
      <>
        <PageHeader
          title="Endpoint Not Found"
          actions={
            <Button variant="outline" size="sm" asChild>
              <Link to="/apis">
                <ArrowLeft className="mr-2 size-4" />
                Back to APIs
              </Link>
            </Button>
          }
        />
        <div className="p-4">
          <p className="text-muted-foreground">
            Endpoint {method} {path} was not found.
          </p>
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={path}
        actions={
          <div className="flex items-center gap-2">
            <MethodBadge method={method as HttpMethod} />
            <Button variant="outline" size="sm" asChild>
              <Link to="/apis">
                <ArrowLeft className="mr-2 size-4" />
                Back
              </Link>
            </Button>
          </div>
        }
      />

      <div className="flex-1 space-y-4 p-4">
        {/* Stats */}
        <Card>
          <CardHeader>
            <CardTitle>Stats (24h)</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Requests</span>
              <span>{endpoint.requests_24h.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Avg Latency</span>
              <span>{endpoint.avg_latency_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">p50 Latency</span>
              <span>{endpoint.p50_latency_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">p95 Latency</span>
              <span>{endpoint.p95_latency_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">p99 Latency</span>
              <span>{endpoint.p99_latency_ms}ms</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Error Rate</span>
              <span>{endpoint.error_rate.toFixed(2)}%</span>
            </div>
          </CardContent>
        </Card>

        {/* Charts placeholder */}
        <Card>
          <CardHeader>
            <CardTitle>Request Volume</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Chart coming soon...
            </p>
          </CardContent>
        </Card>

        {/* Recent errors placeholder */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Errors</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              No recent errors.
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
