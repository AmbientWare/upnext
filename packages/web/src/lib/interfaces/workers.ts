export type WorkerStatus = 'healthy' | 'unhealthy' | 'stopped'

export interface Worker {
  id: string
  status: WorkerStatus
  started_at: string
  last_heartbeat: string
  functions: string[]
  concurrency: number
  active_jobs: number
  jobs_processed: number
  jobs_failed: number
  hostname: string | null
  version: string | null
}

export interface WorkersListResponse {
  workers: Worker[]
  total: number
}
