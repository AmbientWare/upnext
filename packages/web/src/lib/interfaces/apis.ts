export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface ApiEndpoint {
  method: HttpMethod
  path: string
  requests_24h: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
  error_rate: number
  last_request_at: string | null
}

export interface ApisListResponse {
  endpoints: ApiEndpoint[]
  total: number
}

export interface ApiDetailResponse extends ApiEndpoint {
  hourly_stats: {
    hour: string
    requests: number
    errors: number
    avg_latency_ms: number
  }[]
  recent_errors: {
    status_code: number
    message: string
    timestamp: string
  }[]
}
