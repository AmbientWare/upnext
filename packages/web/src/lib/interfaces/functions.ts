import type { Run } from './runs'

export type FunctionType = 'task' | 'cron' | 'trigger'

export interface FunctionInfo {
  name: string
  type: FunctionType
  // Task config
  timeout: number
  max_retries: number
  retry_delay: number
  // Cron config (if type === 'cron')
  schedule?: string
  timezone?: string
  next_run_at?: string
  // Trigger config (if type === 'trigger')
  pattern?: string
  // Stats
  runs_24h: number
  success_rate: number
  avg_duration_ms: number
  p95_duration_ms: number | null
  last_run_at: string | null
  last_run_status: string | null
}

export interface FunctionsListResponse {
  functions: FunctionInfo[]
  total: number
}

export interface FunctionDetailResponse extends FunctionInfo {
  recent_runs: Run[]
  hourly_stats: {
    hour: string
    success: number
    failure: number
  }[]
}
