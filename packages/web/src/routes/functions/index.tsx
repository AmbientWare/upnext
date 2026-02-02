import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { RelativeTime } from '@/components/shared/RelativeTime'
import { getFunctions } from '@/lib/server/functions'
import type { FunctionInfo } from '@/lib/interfaces'

export const Route = createFileRoute('/functions/')({
  component: FunctionsPage,
  loader: async () => {
    try {
      return await getFunctions()
    } catch {
      return { functions: [], total: 0 }
    }
  },
})

function FunctionsPage() {
  const data = Route.useLoaderData()
  const functions = data.functions

  const tasks = functions.filter((f) => f.type === 'task')
  const crons = functions.filter((f) => f.type === 'cron')
  const triggers = functions.filter((f) => f.type === 'trigger')

  return (
    <>
      <PageHeader title="Functions" description="Registered tasks, crons, and triggers" />

      <div className="flex-1 p-4">
        <Tabs defaultValue="tasks">
          <TabsList>
            <TabsTrigger value="tasks">
              Tasks <Badge variant="secondary" className="ml-2">{tasks.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="crons">
              Crons <Badge variant="secondary" className="ml-2">{crons.length}</Badge>
            </TabsTrigger>
            <TabsTrigger value="triggers">
              Triggers <Badge variant="secondary" className="ml-2">{triggers.length}</Badge>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="tasks" className="mt-4">
            <FunctionsTable functions={tasks} type="task" />
          </TabsContent>

          <TabsContent value="crons" className="mt-4">
            <CronsTable crons={crons} />
          </TabsContent>

          <TabsContent value="triggers" className="mt-4">
            <TriggersTable triggers={triggers} />
          </TabsContent>
        </Tabs>
      </div>
    </>
  )
}

function FunctionsTable({ functions, type }: { functions: FunctionInfo[]; type: string }) {
  if (functions.length === 0) {
    return (
      <div className="rounded-md border p-8 text-center text-muted-foreground">
        No {type}s registered yet.
      </div>
    )
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Runs (24h)</TableHead>
            <TableHead>Success Rate</TableHead>
            <TableHead>Avg Duration</TableHead>
            <TableHead>Last Run</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {functions.map((fn) => (
            <TableRow key={fn.name}>
              <TableCell>
                <Link
                  to="/functions/$name"
                  params={{ name: fn.name }}
                  className="font-medium text-primary hover:underline"
                >
                  {fn.name}
                </Link>
              </TableCell>
              <TableCell>{fn.runs_24h}</TableCell>
              <TableCell>
                <SuccessRateBadge rate={fn.success_rate} />
              </TableCell>
              <TableCell>{fn.avg_duration_ms ? `${(fn.avg_duration_ms / 1000).toFixed(2)}s` : '-'}</TableCell>
              <TableCell>
                <RelativeTime date={fn.last_run_at} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function CronsTable({ crons }: { crons: FunctionInfo[] }) {
  if (crons.length === 0) {
    return (
      <div className="rounded-md border p-8 text-center text-muted-foreground">
        No crons registered yet.
      </div>
    )
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Schedule</TableHead>
            <TableHead>Next Run</TableHead>
            <TableHead>Last Run</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {crons.map((cron) => (
            <TableRow key={cron.name}>
              <TableCell>
                <Link
                  to="/functions/$name"
                  params={{ name: cron.name }}
                  className="font-medium text-primary hover:underline"
                >
                  {cron.name}
                </Link>
              </TableCell>
              <TableCell className="font-mono text-sm">{cron.schedule}</TableCell>
              <TableCell>
                <RelativeTime date={cron.next_run_at || null} />
              </TableCell>
              <TableCell>
                <RelativeTime date={cron.last_run_at} />
              </TableCell>
              <TableCell>
                {cron.last_run_status === 'complete' ? (
                  <Badge variant="outline" className="border-green-500 text-green-500">OK</Badge>
                ) : cron.last_run_status === 'failed' ? (
                  <Badge variant="destructive">Failed</Badge>
                ) : (
                  <Badge variant="secondary">-</Badge>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function TriggersTable({ triggers }: { triggers: FunctionInfo[] }) {
  if (triggers.length === 0) {
    return (
      <div className="rounded-md border p-8 text-center text-muted-foreground">
        No triggers registered yet.
      </div>
    )
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Pattern</TableHead>
            <TableHead>Runs (24h)</TableHead>
            <TableHead>Last Triggered</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {triggers.map((trigger) => (
            <TableRow key={trigger.name}>
              <TableCell>
                <Link
                  to="/functions/$name"
                  params={{ name: trigger.name }}
                  className="font-medium text-primary hover:underline"
                >
                  {trigger.name}
                </Link>
              </TableCell>
              <TableCell className="font-mono text-sm">{trigger.pattern}</TableCell>
              <TableCell>{trigger.runs_24h}</TableCell>
              <TableCell>
                <RelativeTime date={trigger.last_run_at} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function SuccessRateBadge({ rate }: { rate: number }) {
  if (rate >= 95) {
    return <Badge variant="outline" className="border-green-500 text-green-500">{rate.toFixed(1)}%</Badge>
  }
  if (rate >= 80) {
    return <Badge variant="outline" className="border-yellow-500 text-yellow-500">{rate.toFixed(1)}%</Badge>
  }
  return <Badge variant="destructive">{rate.toFixed(1)}%</Badge>
}
