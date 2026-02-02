import type { Run } from './runs'

export interface DashboardStats {
  runs: {
    total_24h: number
    success_rate: number
    active_count: number
    queued_count: number
  }
  workers: {
    total: number
    healthy: number
    unhealthy: number
  }
  apis: {
    requests_24h: number
    avg_latency_ms: number
    error_rate: number
  }
  recent_runs: Run[]
  recent_failures: Run[]
}
