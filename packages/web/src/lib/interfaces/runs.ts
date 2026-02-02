export type RunStatus =
  | 'pending'
  | 'queued'
  | 'active'
  | 'complete'
  | 'failed'
  | 'cancelled'
  | 'retrying'

// JSON-serializable value type for TanStack Start compatibility
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue }

export interface StateTransition {
  from_state: string
  to_state: string
  timestamp: string
  worker_id: string | null
  message: string | null
}

export interface Run {
  id: string
  function: string
  status: RunStatus
  queue: string
  attempts: number
  max_retries: number
  worker_id: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  duration_ms: number | null
  progress: number
  result: JsonValue
  error: string | null
  kwargs: Record<string, JsonValue>
  metadata: Record<string, JsonValue>
  state_history: StateTransition[]
}

export interface RunsListResponse {
  jobs: Run[]
  total: number
  has_more: boolean
}

export interface RunsStatsResponse {
  total: number
  success_count: number
  failure_count: number
  cancelled_count: number
  success_rate: number
  avg_duration_ms: number | null
}

export interface RunsFilters {
  status?: RunStatus | RunStatus[]
  function?: string
  worker_id?: string
  queue?: string
  after?: string
  before?: string
  limit?: number
  offset?: number
}
