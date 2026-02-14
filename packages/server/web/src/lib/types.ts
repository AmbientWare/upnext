/**
 * TypeScript types matching the backend API schemas.
 * @see packages/shared/src/shared/schemas.py
 */

// =============================================================================
// Common Types
// =============================================================================

export type FunctionType = 'task' | 'cron' | 'event';
export type JobType = 'task' | 'cron' | 'event';
export type MissedRunPolicy = 'catch_up' | 'latest_only' | 'skip';
export interface DispatchReasonMetrics {
  paused: number;
  rate_limited: number;
  no_capacity: number;
  cancelled: number;
  retrying: number;
}
export type JobStatus =
  | 'pending'
  | 'queued'
  | 'active'
  | 'complete'
  | 'failed'
  | 'cancelled'
  | 'retrying';

// =============================================================================
// Job Schemas
// =============================================================================

export interface TaskJobSource {
  type: 'task';
}

export interface CronJobSource {
  type: 'cron';
  schedule: string;
  cron_window_at: number | null;
  startup_reconciled: boolean;
  startup_policy: string | null;
}

export interface EventJobSource {
  type: 'event';
  event_pattern: string;
  event_handler_name: string;
}

export type JobSource = TaskJobSource | CronJobSource | EventJobSource;

export interface Job {
  id: string;
  function: string;
  function_name: string;
  job_type: JobType;
  source: JobSource;
  status: JobStatus;
  created_at: string | null;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  attempts: number;
  max_retries: number;
  timeout: number | null;
  worker_id: string | null;
  parent_id: string | null;
  root_id: string;
  progress: number;
  kwargs: Record<string, unknown>;
  checkpoint: Record<string, unknown> | null;
  checkpoint_at: string | null;
  dlq_replayed_from: string | null;
  dlq_failed_at: string | null;
  result: unknown;
  error: string | null;
  duration_ms: number | null;
}

export interface JobListResponse {
  jobs: Job[];
  total: number;
  has_more: boolean;
  next_cursor: string | null;
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

export interface JobTrendsSnapshotEvent {
  type: "jobs.trends.snapshot";
  at: string;
  trends: JobTrendsResponse;
}

// =============================================================================
// Artifact Schemas
// =============================================================================

export interface Artifact {
  id: string;
  job_id: string;
  name: string;
  type: string;
  content_type: string | null;
  size_bytes: number | null;
  sha256: string | null;
  storage_backend: string;
  storage_key: string;
  status: string;
  error: string | null;
  created_at: string;
}

export interface ArtifactListResponse {
  artifacts: Artifact[];
  total: number;
}

export interface ArtifactStreamEvent {
  type: "artifact.created" | "artifact.queued" | "artifact.promoted" | "artifact.deleted";
  at: string;
  job_id: string;
  artifact_id: string | null;
  pending_id: string | null;
  artifact: Artifact | null;
}

// =============================================================================
// Run Schema (simplified job for lists)
// =============================================================================

export interface Run {
  id: string;
  function: string;
  function_name: string;
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
  function_names: Record<string, string>;
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
  function_names: Record<string, string>;
  concurrency: number;
}

export interface WorkersListResponse {
  workers: WorkerInfo[];
  total: number;
}

export interface WorkersSnapshotEvent {
  type: "workers.snapshot";
  at: string;
  workers: WorkersListResponse;
}

export interface WorkerStats {
  total: number;
}

// =============================================================================
// Function Schemas
// =============================================================================

export interface FunctionInfo {
  key: string;
  name: string;
  type: FunctionType;
  active: boolean;
  paused: boolean;
  // Task config
  timeout: number | null;
  max_retries: number | null;
  retry_delay: number | null;
  rate_limit: string | null;
  max_concurrency: number | null;
  routing_group: string | null;
  group_max_concurrency: number | null;
  // Cron config
  schedule: string | null;
  next_run_at: string | null;
  missed_run_policy: MissedRunPolicy | null;
  max_catch_up_seconds: number | null;
  // Event config
  pattern: string | null;
  // Workers currently handling this function
  workers: string[];
  // Stats
  runs_24h: number;
  success_rate: number;
  avg_duration_ms: number;
  p95_duration_ms: number | null;
  avg_wait_ms: number | null;
  p95_wait_ms: number | null;
  queue_backlog: number;
  dispatch_reasons: DispatchReasonMetrics;
  last_run_at: string | null;
  last_run_status: string | null;
}

export interface FunctionsListResponse {
  functions: FunctionInfo[];
  total: number;
}

export interface FunctionDetailResponse extends FunctionInfo {
  recent_runs: Run[];
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

export interface ApiEndpoint {
  api_name?: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  requests_24h: number;
  requests_per_min: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  error_rate: number;
  success_rate: number;
  client_error_rate: number;
  server_error_rate: number;
  status_2xx: number;
  status_4xx: number;
  status_5xx: number;
  last_request_at: string | null;
}

export interface ApiOverview {
  name: string;
  docs_url: string | null;
  active: boolean;
  instance_count: number;
  instances: ApiInstance[];
  endpoint_count: number;
  requests_24h: number;
  requests_per_min: number;
  avg_latency_ms: number;
  error_rate: number;
  success_rate: number;
  client_error_rate: number;
  server_error_rate: number;
}

export interface ApiPageResponse {
  api: ApiOverview;
  endpoints: ApiEndpoint[];
  total_endpoints: number;
}

export interface ApisListResponse {
  apis: ApiInfo[];
  total: number;
}

export interface EndpointsListResponse {
  endpoints: ApiEndpoint[];
  total: number;
}

export interface ApiRequestEvent {
  id: string;
  at: string;
  api_name: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  status: number;
  latency_ms: number;
  instance_id: string | null;
  sampled: boolean;
}

export interface ApiRequestEventsResponse {
  events: ApiRequestEvent[];
  total: number;
  has_more: boolean;
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

export interface ApiTrendsSnapshotEvent {
  type: "apis.trends.snapshot";
  at: string;
  trends: ApiTrendsResponse;
}

export interface ApisSnapshotEvent {
  type: "apis.snapshot";
  at: string;
  apis: ApisListResponse;
}

export interface ApiSnapshotEvent {
  type: "api.snapshot";
  at: string;
  api: ApiPageResponse;
}

export interface ApiRequestSnapshotEvent {
  type: "api.request";
  at: string;
  request: ApiRequestEvent;
}

// =============================================================================
// Dashboard Schemas
// =============================================================================

export interface RunStats {
  total: number;
  success_rate: number;
  window_minutes: number;
  jobs_per_min: number;
}

export interface QueueStats {
  running: number;
  waiting: number;
  claimed: number;
  scheduled_due: number;
  scheduled_future: number;
  backlog: number;
  capacity: number;
  total: number;
}

export interface ApiStats {
  requests: number;
  avg_latency_ms: number;
  error_rate: number;
  window_minutes: number;
  requests_per_min: number;
}

export interface TopFailingFunction {
  key: string;
  name: string;
  runs: number;
  failures: number;
  failure_rate: number;
  last_run_at: string | null;
}

export interface OldestQueuedJob {
  id: string;
  function: string;
  function_name: string;
  queued_at: string;
  age_seconds: number;
  source: string;
}

export interface StuckActiveJob {
  id: string;
  function: string;
  function_name: string;
  worker_id: string | null;
  started_at: string;
  age_seconds: number;
}

export interface DashboardStats {
  runs: RunStats;
  queue: QueueStats;
  workers: WorkerStats;
  apis: ApiStats;
  recent_runs: Run[];
  recent_failures: Run[];
  top_failing_functions: TopFailingFunction[];
  oldest_queued_jobs: OldestQueuedJob[];
  stuck_active_jobs: StuckActiveJob[];
}

// =============================================================================
// Admin Schemas
// =============================================================================

export interface AdminUser {
  id: string;
  username: string;
  is_admin: boolean;
  api_key_count: number;
  created_at: string;
}

export interface AdminUserCreated extends AdminUser {
  api_key: AdminApiKeyCreated;
}

export interface AdminUsersListResponse {
  users: AdminUser[];
  total: number;
}

export interface AdminApiKey {
  id: string;
  user_id: string;
  key_prefix: string;
  name: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface AdminApiKeyCreated {
  id: string;
  user_id: string;
  key_prefix: string;
  name: string;
  is_active: boolean;
  raw_key: string;
}

export interface AdminApiKeysListResponse {
  api_keys: AdminApiKey[];
  total: number;
}

// =============================================================================
// Secrets Schemas
// =============================================================================

export interface SecretInfo {
  id: string;
  name: string;
  keys: string[];
  created_at: string;
  updated_at: string;
}

export interface SecretDetail {
  id: string;
  name: string;
  data: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface SecretsListResponse {
  secrets: SecretInfo[];
  total: number;
}

export interface AuthVerifyResponse {
  ok: boolean;
  user: {
    id: string;
    username: string;
    is_admin: boolean;
  } | null;
}
