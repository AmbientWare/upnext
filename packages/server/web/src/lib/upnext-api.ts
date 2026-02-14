/**
 * UpNext API client for the web dashboard.
 * All API calls to the backend go through this module.
 */

import type {
  AdminApiKey,
  AdminApiKeyCreated,
  AdminApiKeysListResponse,
  AdminUser,
  AdminUserCreated,
  AdminUsersListResponse,
  ArtifactListResponse,
  ApisListResponse,
  ApiPageResponse,
  ApiRequestEventsResponse,
  ApiTrendsResponse,
  AuthVerifyResponse,
  DashboardStats,
  FunctionDetailResponse,
  Job,
  FunctionsListResponse,
  JobListResponse,
  JobTrendsResponse,
  SecretDetail,
  SecretsListResponse,
  WorkersListResponse,
} from "./types";
import { getStoredApiKey } from "./auth";
import { env } from "./env";

const API_BASE = env.VITE_API_BASE_URL;
const API_REQUEST_TIMEOUT_MS = 10_000;

// =============================================================================
// Error Handling
// =============================================================================

export class ApiError extends Error {
  status: number;
  statusText: string;

  constructor(status: number, statusText: string, message?: string) {
    super(message || `API Error: ${status} ${statusText}`);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
  }
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (typeof error === "object" &&
      error !== null &&
      "name" in error &&
      (error as { name?: string }).name === "AbortError")
  );
}

async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => {
    controller.abort();
  }, API_REQUEST_TIMEOUT_MS);

  const headers = new Headers(init?.headers);
  const apiKey = getStoredApiKey();
  if (apiKey) {
    headers.set("Authorization", `Bearer ${apiKey}`);
  }

  try {
    return await fetch(url, { ...init, headers, signal: controller.signal });
  } catch (error) {
    if (isAbortError(error)) {
      throw new ApiError(
        408,
        "Request Timeout",
        `Request timed out after ${API_REQUEST_TIMEOUT_MS}ms`
      );
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, text);
  }
  return response.json();
}

// =============================================================================
// Dashboard
// =============================================================================

export interface GetDashboardStatsParams {
  window_minutes?: 1 | 5 | 15 | 60 | 1440;
  failing_min_rate?: number;
}

export async function getDashboardStats(
  params: GetDashboardStatsParams = {}
): Promise<DashboardStats> {
  const searchParams = new URLSearchParams();
  if (params.window_minutes !== undefined) {
    searchParams.set("window_minutes", String(params.window_minutes));
  }
  if (params.failing_min_rate !== undefined) {
    searchParams.set("failing_min_rate", String(params.failing_min_rate));
  }
  const query = searchParams.toString();
  const response = await apiFetch(
    `${API_BASE}/dashboard/stats${query ? `?${query}` : ""}`
  );
  return handleResponse<DashboardStats>(response);
}

// =============================================================================
// Jobs
// =============================================================================

export interface GetJobsParams {
  function?: string;
  status?: string[];
  worker_id?: string;
  after?: string;
  before?: string;
  limit?: number;
  cursor?: string;
}

export async function getJobs(params: GetJobsParams = {}): Promise<JobListResponse> {
  const searchParams = new URLSearchParams();

  if (params.function) searchParams.set("function", params.function);
  if (params.status?.length) {
    params.status.forEach((s) => searchParams.append("status", s));
  }
  if (params.worker_id) searchParams.set("worker_id", params.worker_id);
  if (params.after) searchParams.set("after", params.after);
  if (params.before) searchParams.set("before", params.before);
  if (params.limit !== undefined) searchParams.set("limit", String(params.limit));
  if (params.cursor) searchParams.set("cursor", params.cursor);

  const query = searchParams.toString();
  const url = `${API_BASE}/jobs${query ? `?${query}` : ""}`;

  const response = await apiFetch(url);
  return handleResponse<JobListResponse>(response);
}

export interface GetJobTrendsParams {
  hours?: number;
  function?: string;
  type?: string;
}

export async function getJobTrends(params: GetJobTrendsParams = {}): Promise<JobTrendsResponse> {
  const searchParams = new URLSearchParams();

  if (params.hours !== undefined) searchParams.set("hours", String(params.hours));
  if (params.function) searchParams.set("function", params.function);
  if (params.type) searchParams.set("type", params.type);

  const query = searchParams.toString();
  const url = `${API_BASE}/jobs/trends${query ? `?${query}` : ""}`;

  const response = await apiFetch(url);
  return handleResponse<JobTrendsResponse>(response);
}

export async function getJob(jobId: string): Promise<Job> {
  const response = await apiFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`);
  return handleResponse<Job>(response);
}

export async function getJobTimeline(jobId: string): Promise<JobListResponse> {
  const response = await apiFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/timeline`);
  return handleResponse<JobListResponse>(response);
}

export async function getJobArtifacts(jobId: string): Promise<ArtifactListResponse> {
  const response = await apiFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/artifacts`);
  return handleResponse<ArtifactListResponse>(response);
}

export interface JobCancelResponse {
  job_id: string;
  cancelled: boolean;
  deleted_stream_entries?: number;
}

export interface JobRetryResponse {
  job_id: string;
  retried: boolean;
}

export async function cancelJob(jobId: string): Promise<JobCancelResponse> {
  const response = await apiFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
  return handleResponse<JobCancelResponse>(response);
}

export async function retryJob(jobId: string): Promise<JobRetryResponse> {
  const response = await apiFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  });
  return handleResponse<JobRetryResponse>(response);
}

function getArtifactContentUrl(
  artifactId: string | number,
  options: { download?: boolean } = {}
): string {
  const searchParams = new URLSearchParams();
  if (options.download) {
    searchParams.set("download", "1");
  }
  const query = searchParams.toString();
  return `${API_BASE}/artifacts/${artifactId}/content${query ? `?${query}` : ""}`;
}

/**
 * Fetch artifact content as a blob via apiFetch (sends Authorization header).
 * Returns an object URL suitable for <img src>, <iframe src>, <a href>, etc.
 * Callers must revoke the URL when done via URL.revokeObjectURL().
 */
export async function fetchArtifactBlobUrl(
  artifactId: string | number,
  options: { download?: boolean } = {}
): Promise<string> {
  const url = getArtifactContentUrl(artifactId, options);
  const response = await apiFetch(url);
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, text);
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

/**
 * Fetch artifact content as text via apiFetch (sends Authorization header).
 */
export async function fetchArtifactText(
  artifactId: string | number,
  options: { signal?: AbortSignal } = {}
): Promise<{ text: string; contentLength: number | null }> {
  const url = getArtifactContentUrl(artifactId);
  const response = await apiFetch(url, { signal: options.signal });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, text);
  }
  const contentLengthHeader = response.headers.get("content-length");
  const contentLength = contentLengthHeader ? Number(contentLengthHeader) : null;
  const text = await response.text();
  return { text, contentLength };
}

// =============================================================================
// Workers
// =============================================================================

export async function getWorkers(): Promise<WorkersListResponse> {
  const response = await apiFetch(`${API_BASE}/workers`);
  return handleResponse<WorkersListResponse>(response);
}

// =============================================================================
// Functions
// =============================================================================

export interface GetFunctionsParams {
  type?: 'task' | 'cron' | 'event';
}

export async function getFunctions(params: GetFunctionsParams = {}): Promise<FunctionsListResponse> {
  const searchParams = new URLSearchParams();

  if (params.type) searchParams.set("type", params.type);

  const query = searchParams.toString();
  const url = `${API_BASE}/functions${query ? `?${query}` : ""}`;

  const response = await apiFetch(url);
  return handleResponse<FunctionsListResponse>(response);
}

export async function getFunction(name: string): Promise<FunctionDetailResponse> {
  const response = await apiFetch(`${API_BASE}/functions/${encodeURIComponent(name)}`);
  return handleResponse<FunctionDetailResponse>(response);
}

export interface FunctionPauseResponse {
  key: string;
  paused: boolean;
}

export async function pauseFunction(name: string): Promise<FunctionPauseResponse> {
  const response = await apiFetch(`${API_BASE}/functions/${encodeURIComponent(name)}/pause`, {
    method: "POST",
  });
  return handleResponse<FunctionPauseResponse>(response);
}

export async function resumeFunction(name: string): Promise<FunctionPauseResponse> {
  const response = await apiFetch(`${API_BASE}/functions/${encodeURIComponent(name)}/resume`, {
    method: "POST",
  });
  return handleResponse<FunctionPauseResponse>(response);
}

// =============================================================================
// API Endpoints
// =============================================================================

export async function getApis(): Promise<ApisListResponse> {
  const response = await apiFetch(`${API_BASE}/apis`);
  return handleResponse<ApisListResponse>(response);
}

export interface GetApiTrendsParams {
  hours?: number;
}

export async function getApiTrends(params: GetApiTrendsParams = {}): Promise<ApiTrendsResponse> {
  const searchParams = new URLSearchParams();

  if (params.hours !== undefined) searchParams.set("hours", String(params.hours));

  const query = searchParams.toString();
  const url = `${API_BASE}/apis/trends${query ? `?${query}` : ""}`;

  const response = await apiFetch(url);
  return handleResponse<ApiTrendsResponse>(response);
}

export async function getApi(name: string): Promise<ApiPageResponse> {
  const response = await apiFetch(`${API_BASE}/apis/${encodeURIComponent(name)}`);
  return handleResponse<ApiPageResponse>(response);
}

export interface GetApiRequestEventsParams {
  api_name?: string;
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path?: string;
  status?: number;
  instance_id?: string;
  after?: string;
  before?: string;
  limit?: number;
  offset?: number;
}

export async function getApiRequestEvents(
  params: GetApiRequestEventsParams = {}
): Promise<ApiRequestEventsResponse> {
  const searchParams = new URLSearchParams();
  if (params.api_name) searchParams.set("api_name", params.api_name);
  if (params.method) searchParams.set("method", params.method);
  if (params.path) searchParams.set("path", params.path);
  if (params.status !== undefined) searchParams.set("status", String(params.status));
  if (params.instance_id) searchParams.set("instance_id", params.instance_id);
  if (params.after) searchParams.set("after", params.after);
  if (params.before) searchParams.set("before", params.before);
  if (params.limit !== undefined) searchParams.set("limit", String(params.limit));
  if (params.offset !== undefined) searchParams.set("offset", String(params.offset));

  const query = searchParams.toString();
  const response = await apiFetch(`${API_BASE}/apis/events${query ? `?${query}` : ""}`);
  return handleResponse<ApiRequestEventsResponse>(response);
}

// =============================================================================
// Auth
// =============================================================================

export async function verifyAuth(): Promise<AuthVerifyResponse> {
  const response = await apiFetch(`${API_BASE}/auth/verify`, { method: "POST" });
  return handleResponse<AuthVerifyResponse>(response);
}

// =============================================================================
// Admin
// =============================================================================

export async function getAdminUsers(): Promise<AdminUsersListResponse> {
  const response = await apiFetch(`${API_BASE}/admin/users`);
  return handleResponse<AdminUsersListResponse>(response);
}

export async function createAdminUser(data: {
  username: string;
  is_admin: boolean;
}): Promise<AdminUserCreated> {
  const response = await apiFetch(`${API_BASE}/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse<AdminUserCreated>(response);
}

export async function deleteAdminUser(userId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, text);
  }
}

export async function updateAdminUser(
  userId: string,
  data: { is_admin?: boolean }
): Promise<AdminUser> {
  const response = await apiFetch(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
  return handleResponse<AdminUser>(response);
}

export async function getAdminUserApiKeys(
  userId: string
): Promise<AdminApiKeysListResponse> {
  const response = await apiFetch(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}/api-keys`
  );
  return handleResponse<AdminApiKeysListResponse>(response);
}

export async function createAdminApiKey(
  userId: string,
  data: { name: string }
): Promise<AdminApiKeyCreated> {
  const response = await apiFetch(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}/api-keys`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
  return handleResponse<AdminApiKeyCreated>(response);
}

export async function deleteAdminApiKey(
  userId: string,
  keyId: string
): Promise<void> {
  const response = await apiFetch(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}/api-keys/${encodeURIComponent(keyId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, text);
  }
}

export async function rotateAdminApiKey(
  userId: string
): Promise<AdminApiKeyCreated> {
  const response = await apiFetch(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}/rotate-api-key`,
    { method: "POST" }
  );
  return handleResponse<AdminApiKeyCreated>(response);
}

export async function toggleAdminApiKey(
  userId: string,
  keyId: string,
  data: { is_active: boolean }
): Promise<AdminApiKey> {
  const response = await apiFetch(
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}/api-keys/${encodeURIComponent(keyId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
  return handleResponse<AdminApiKey>(response);
}

// =============================================================================
// Secrets
// =============================================================================

export async function getSecrets(): Promise<SecretsListResponse> {
  const response = await apiFetch(`${API_BASE}/secrets`);
  return handleResponse<SecretsListResponse>(response);
}

export async function getSecret(secretId: string): Promise<SecretDetail> {
  const response = await apiFetch(
    `${API_BASE}/secrets/${encodeURIComponent(secretId)}`
  );
  return handleResponse<SecretDetail>(response);
}

export async function createSecret(data: {
  name: string;
  data: Record<string, string>;
}): Promise<SecretDetail> {
  const response = await apiFetch(`${API_BASE}/secrets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse<SecretDetail>(response);
}

export async function updateSecret(
  secretId: string,
  data: { name?: string; data?: Record<string, string> }
): Promise<SecretDetail> {
  const response = await apiFetch(
    `${API_BASE}/secrets/${encodeURIComponent(secretId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
  return handleResponse<SecretDetail>(response);
}

export async function deleteSecret(secretId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE}/secrets/${encodeURIComponent(secretId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, response.statusText, text);
  }
}

// =============================================================================
// Query Keys (for TanStack Query)
// =============================================================================

export const queryKeys = {
  dashboard: ["dashboard"] as const,
  dashboardStats: ["dashboard", "stats"] as const,
  dashboardStatsWithParams: (params?: GetDashboardStatsParams) =>
    ["dashboard", "stats", params] as const,

  jobs: (params?: GetJobsParams) => ["jobs", params] as const,
  job: (jobId: string) => ["jobs", "job", jobId] as const,
  jobTimeline: (jobId: string) => ["jobs", "timeline", jobId] as const,
  jobArtifacts: (jobId: string) => ["jobs", "artifacts", jobId] as const,
  jobTrends: (params?: GetJobTrendsParams) => ["jobs", "trends", params] as const,

  workers: ["workers"] as const,

  functions: (params?: GetFunctionsParams) => ["functions", params] as const,
  function: (name: string) => ["functions", name] as const,

  apis: ["apis"] as const,
  apiRequestEvents: (params?: GetApiRequestEventsParams) => ["apis", "events", params] as const,
  api: (name: string) => ["apis", "api", name] as const,
  apiTrends: (params?: GetApiTrendsParams) => ["apis", "trends", params] as const,

  adminUsers: ["admin", "users"] as const,
  adminUserApiKeys: (userId: string) =>
    ["admin", "users", userId, "api-keys"] as const,
  secrets: ["secrets"] as const,
  secret: (secretId: string) => ["secrets", secretId] as const,
};
