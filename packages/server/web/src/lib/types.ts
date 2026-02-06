/**
 * TypeScript types matching the backend API schemas.
 * @see packages/shared/src/shared/schemas.py
 */

// =============================================================================
// Common Types
// =============================================================================

export type FunctionType = 'task' | 'cron' | 'event';
export type JobStatus = 'active' | 'complete' | 'failed' | 'retrying';
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

// =============================================================================
// Job Schemas
// =============================================================================

export interface Job {
  id: string;
  function: string;
  status: JobStatus;
  created_at: string | null;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  attempts: number;
  max_retries: number;
  timeout: number | null;
  worker_id: string | null;
  progress: number;
  kwargs: Record<string, unknown>;
  metadata: Record<string, unknown>;
  result: unknown;
  error: string | null;
  duration_ms: number | null;
}

export interface JobListResponse {
  jobs: Job[];
  total: number;
  has_more: boolean;
}

export interface JobStatsResponse {
  total: number;
  success_count: number;
  failure_count: number;
  cancelled_count: number;
  success_rate: number;
  avg_duration_ms: number | null;
}

export interface JobTrendHour {
  hour: string;
  complete: number;
  failed: number;
  retrying: number;
  active: number;
}

export interface JobTrendsResponse {
  hourly: JobTrendHour[];
}

// =============================================================================
// Run Schema (simplified job for lists)
// =============================================================================

export interface Run {
  id: string;
  function: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
  worker_id: string | null;
  attempts: number;
  progress: number;
}

// =============================================================================
// Worker Schemas
// =============================================================================

export interface WorkerInstance {
  id: string;
  worker_name: string;
  started_at: string;
  last_heartbeat: string;
  functions: string[];
  concurrency: number;
  active_jobs: number;
  jobs_processed: number;
  jobs_failed: number;
  hostname: string | null;
}

export interface WorkerInfo {
  name: string;
  active: boolean;
  instance_count: number;
  instances: WorkerInstance[];
  functions: string[];
  concurrency: number;
}

export interface WorkersListResponse {
  workers: WorkerInfo[];
  total: number;
}

export interface WorkerStats {
  total: number;
}

// =============================================================================
// Function Schemas
// =============================================================================

export interface FunctionInfo {
  name: string;
  type: FunctionType;
  active: boolean;
  // Task config
  timeout: number | null;
  max_retries: number | null;
  retry_delay: number | null;
  // Cron config
  schedule: string | null;
  timezone: string | null;
  next_run_at: string | null;
  // Event config
  pattern: string | null;
  // Stream config
  source: string | null;
  batch_size: number | null;
  batch_timeout: number | null;
  max_concurrency: number | null;
  // Workers currently handling this function
  workers: string[];
  // Stats
  runs_24h: number;
  success_rate: number;
  avg_duration_ms: number;
  p95_duration_ms: number | null;
  last_run_at: string | null;
  last_run_status: string | null;
  // Stream-specific stats
  events_processed_24h: number | null;
  batches_24h: number | null;
}

export interface FunctionsListResponse {
  functions: FunctionInfo[];
  total: number;
}

export interface HourlyStat {
  hour: string;
  success: number;
  failure: number;
}

export interface FunctionDetailResponse extends FunctionInfo {
  recent_runs: Run[];
  hourly_stats: HourlyStat[];
}

// =============================================================================
// API Schemas
// =============================================================================

export interface ApiInstance {
  id: string;
  api_name: string;
  started_at: string;
  last_heartbeat: string;
  host: string;
  port: number;
  endpoints: string[];
  hostname: string | null;
}

export interface ApiInfo {
  name: string;
  active: boolean;
  instance_count: number;
  instances: ApiInstance[];
  endpoint_count: number;
  requests_24h: number;
  avg_latency_ms: number;
  error_rate: number;
  requests_per_min: number;
}

export interface ApisListResponse {
  apis: ApiInfo[];
  total: number;
}

export interface ApiEndpoint {
  method: HttpMethod;
  path: string;
  requests_24h: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  error_rate: number;
  last_request_at: string | null;
}

export interface ApiHourlyStat {
  hour: string;
  requests: number;
  errors: number;
  avg_latency_ms: number;
}

export interface ApiTrendHour {
  hour: string;
  success_2xx: number;
  client_4xx: number;
  server_5xx: number;
}

export interface ApiTrendsResponse {
  hourly: ApiTrendHour[];
}

// =============================================================================
// Dashboard Schemas
// =============================================================================

export interface RunStats {
  total_24h: number;
  success_rate: number;
  active_count: number;
}

export interface ApiStats {
  requests_24h: number;
  avg_latency_ms: number;
  error_rate: number;
}

export interface DashboardStats {
  runs: RunStats;
  workers: WorkerStats;
  apis: ApiStats;
  recent_runs: Run[];
  recent_failures: Run[];
}

// =============================================================================
// Artifact Schemas
// =============================================================================

export interface Artifact {
  id: number;
  job_id: string;
  name: string;
  type: string;
  size_bytes: number | null;
  data: unknown;
  path: string | null;
  created_at: string;
}

export interface ArtifactListResponse {
  artifacts: Artifact[];
  total: number;
}
