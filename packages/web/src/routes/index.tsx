import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { RelativeTime } from '@/components/shared/RelativeTime'
import { Play, CheckCircle, Server, Globe, ArrowRight } from 'lucide-react'
import { getDashboardStats } from '@/lib/server/dashboard'
import type { DashboardStats } from '@/lib/interfaces'

export const Route = createFileRoute('/')({
  component: Dashboard,
  loader: async () => {
    try {
      return await getDashboardStats()
    } catch {
      // Return fallback stats if API is unavailable
      return {
        runs: { total_24h: 0, success_rate: 0, active_count: 0, queued_count: 0 },
        workers: { total: 0, healthy: 0, unhealthy: 0 },
        apis: { requests_24h: 0, avg_latency_ms: 0, error_rate: 0 },
        recent_runs: [],
        recent_failures: [],
      } satisfies DashboardStats
    }
  },
})

function Dashboard() {
  const stats = Route.useLoaderData()

  return (
    <>
      <PageHeader title="Dashboard" description="Overview of your Conduit deployment" />

      <div className="flex-1 space-y-4 p-4 pt-6">
        {/* Stats Grid */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Runs (24h)</CardTitle>
              <Play className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.runs.total_24h.toLocaleString()}</div>
              <p className="text-xs text-muted-foreground">
                {stats.runs.active_count} active, {stats.runs.queued_count} queued
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
              <CheckCircle className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.runs.success_rate.toFixed(1)}%</div>
              <p className="text-xs text-muted-foreground">
                Last 24 hours
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Workers</CardTitle>
              <Server className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {stats.workers.healthy}/{stats.workers.total}
              </div>
              <p className="text-xs text-muted-foreground">
                {stats.workers.unhealthy > 0 ? `${stats.workers.unhealthy} unhealthy` : 'All healthy'}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">API Requests</CardTitle>
              <Globe className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.apis.requests_24h.toLocaleString()}</div>
              <p className="text-xs text-muted-foreground">
                {stats.apis.avg_latency_ms}ms avg latency
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Activity and Failures */}
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Recent Activity</CardTitle>
              <Link to="/runs" className="text-sm text-muted-foreground hover:text-primary flex items-center gap-1">
                View all <ArrowRight className="size-3" />
              </Link>
            </CardHeader>
            <CardContent>
              {stats.recent_runs && stats.recent_runs.length > 0 ? (
                <div className="space-y-3">
                  {stats.recent_runs.slice(0, 5).map((run) => (
                    <div key={run.id} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <StatusBadge status={run.status} />
                        <Link
                          to="/runs/$id"
                          params={{ id: run.id }}
                          className="font-medium text-sm hover:underline"
                        >
                          {run.function}
                        </Link>
                      </div>
                      <RelativeTime date={run.created_at} className="text-xs text-muted-foreground" />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No recent activity. Run some tasks to see them here.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Recent Failures</CardTitle>
              <Link
                to="/runs"
                search={{ status: 'failed' }}
                className="text-sm text-muted-foreground hover:text-primary flex items-center gap-1"
              >
                View all <ArrowRight className="size-3" />
              </Link>
            </CardHeader>
            <CardContent>
              {stats.recent_failures && stats.recent_failures.length > 0 ? (
                <div className="space-y-3">
                  {stats.recent_failures.slice(0, 5).map((run) => (
                    <div key={run.id} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <StatusBadge status={run.status} />
                        <Link
                          to="/runs/$id"
                          params={{ id: run.id }}
                          className="font-medium text-sm hover:underline"
                        >
                          {run.function}
                        </Link>
                      </div>
                      <RelativeTime date={run.created_at} className="text-xs text-muted-foreground" />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No recent failures. Looking good!
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}
