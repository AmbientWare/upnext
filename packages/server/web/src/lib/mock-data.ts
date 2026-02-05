import type { JobStatus } from "./utils";

export interface Job {
  id: string;
  function: string;
  status: JobStatus;
  scheduledAt: Date;
  startedAt?: Date;
  completedAt?: Date;
  attempts: number;
  maxRetries: number;
  progress?: number;
  workerId?: string;
  error?: string;
  durationMs?: number;
}

export interface Worker {
  id: string;
  name: string;
  hosting: "self-hosted" | "managed";
  status: "healthy" | "unhealthy" | "offline";
  functions: string[];
  concurrency: number;
  activeJobs: number;
  jobsProcessed: number;
  jobsFailed: number;
  lastHeartbeat: Date;
}

export interface TaskFunction {
  name: string;
  type: "task" | "cron" | "event";
  timeout: number;
  maxRetries: number;
  schedule?: string;
  eventPattern?: string;
  runsLast24h: number;
  successRate: number;
  avgDuration: number;
}

export interface DashboardStats {
  totalJobs24h: number;
  completedJobs: number;
  failedJobs: number;
  activeJobs: number;
  queuedJobs: number;
  successRate: number;
  totalWorkers: number;
  healthyWorkers: number;
  avgDuration: number;
  p95Duration: number;
}

export interface Api {
  id: string;
  name: string;
  hosting: "self-hosted" | "managed";
  requestsPerMin: number;
  avgLatencyMs: number;
  errorRate: number;
  status: "healthy" | "degraded" | "down";
}

// Generate mock jobs
export function generateMockJobs(count: number): Job[] {
  const functions = [
    "process_order",
    "send_email",
    "generate_report",
    "sync_inventory",
    "process_payment",
    "update_analytics",
    "cleanup_sessions",
    "index_documents",
    "resize_image",
    "transcode_video",
  ];
  const statuses: JobStatus[] = ["pending", "queued", "active", "complete", "failed", "retrying"];

  return Array.from({ length: count }, (_, i) => {
    const status = statuses[Math.floor(Math.random() * statuses.length)];
    const scheduledAt = new Date(Date.now() - Math.random() * 24 * 60 * 60 * 1000);
    const startedAt = status !== "pending" && status !== "queued" ? new Date(scheduledAt.getTime() + Math.random() * 60000) : undefined;
    const completedAt = status === "complete" || status === "failed" ? new Date((startedAt?.getTime() || scheduledAt.getTime()) + Math.random() * 300000) : undefined;

    return {
      id: `job_${(1000 + i).toString(36)}${Math.random().toString(36).slice(2, 8)}`,
      function: functions[Math.floor(Math.random() * functions.length)],
      status,
      scheduledAt,
      startedAt,
      completedAt,
      attempts: status === "retrying" ? Math.floor(Math.random() * 3) + 1 : 1,
      maxRetries: 3,
      progress: status === "active" ? Math.random() : undefined,
      workerId: startedAt ? `worker_${Math.floor(Math.random() * 4) + 1}` : undefined,
      error: status === "failed" ? "Connection timeout after 30000ms" : undefined,
      durationMs: completedAt && startedAt ? completedAt.getTime() - startedAt.getTime() : undefined,
    };
  });
}

// Generate mock workers
export function generateMockWorkers(): Worker[] {
  return [
    {
      id: "worker_1",
      name: "worker-prod-1",
      hosting: "managed",
      status: "healthy",
      functions: ["process_order", "send_email", "process_payment"],
      concurrency: 10,
      activeJobs: 7,
      jobsProcessed: 15234,
      jobsFailed: 45,
      lastHeartbeat: new Date(Date.now() - 2000),
    },
    {
      id: "worker_2",
      name: "worker-prod-2",
      hosting: "managed",
      status: "healthy",
      functions: ["generate_report", "update_analytics", "sync_inventory"],
      concurrency: 10,
      activeJobs: 4,
      jobsProcessed: 12456,
      jobsFailed: 23,
      lastHeartbeat: new Date(Date.now() - 1500),
    },
    {
      id: "worker_3",
      name: "worker-prod-3",
      hosting: "self-hosted",
      status: "unhealthy",
      functions: ["resize_image", "transcode_video"],
      concurrency: 5,
      activeJobs: 5,
      jobsProcessed: 8934,
      jobsFailed: 156,
      lastHeartbeat: new Date(Date.now() - 35000),
    },
    {
      id: "worker_4",
      name: "worker-prod-4",
      hosting: "self-hosted",
      status: "healthy",
      functions: ["cleanup_sessions", "index_documents"],
      concurrency: 8,
      activeJobs: 2,
      jobsProcessed: 22341,
      jobsFailed: 12,
      lastHeartbeat: new Date(Date.now() - 3000),
    },
  ];
}

// Generate mock functions
export function generateMockFunctions(): TaskFunction[] {
  return [
    { name: "process_order", type: "task", timeout: 300, maxRetries: 3, runsLast24h: 4521, successRate: 99.2, avgDuration: 1250 },
    { name: "send_email", type: "task", timeout: 60, maxRetries: 5, runsLast24h: 12453, successRate: 98.7, avgDuration: 450 },
    { name: "generate_report", type: "cron", timeout: 600, maxRetries: 2, schedule: "0 0 * * *", runsLast24h: 24, successRate: 100, avgDuration: 45000 },
    { name: "sync_inventory", type: "cron", timeout: 300, maxRetries: 3, schedule: "*/15 * * * *", runsLast24h: 96, successRate: 97.9, avgDuration: 8500 },
    { name: "process_payment", type: "task", timeout: 120, maxRetries: 3, runsLast24h: 3245, successRate: 99.8, avgDuration: 2100 },
    { name: "update_analytics", type: "event", timeout: 60, maxRetries: 2, eventPattern: "user.*", runsLast24h: 8923, successRate: 99.5, avgDuration: 320 },
    { name: "cleanup_sessions", type: "cron", timeout: 180, maxRetries: 1, schedule: "0 */6 * * *", runsLast24h: 4, successRate: 100, avgDuration: 12000 },
    { name: "index_documents", type: "task", timeout: 300, maxRetries: 3, runsLast24h: 2156, successRate: 96.3, avgDuration: 5600 },
    { name: "resize_image", type: "task", timeout: 120, maxRetries: 2, runsLast24h: 5432, successRate: 98.1, avgDuration: 890 },
    { name: "transcode_video", type: "task", timeout: 1800, maxRetries: 1, runsLast24h: 234, successRate: 94.5, avgDuration: 125000 },
  ];
}

// Generate mock dashboard stats
export function generateMockStats(): DashboardStats {
  return {
    totalJobs24h: 45678,
    completedJobs: 44234,
    failedJobs: 456,
    activeJobs: 18,
    queuedJobs: 970,
    successRate: 98.7,
    totalWorkers: 4,
    healthyWorkers: 3,
    avgDuration: 2340,
    p95Duration: 8500,
  };
}

// Generate hourly data for charts
export function generateHourlyData(): { hour: string; completed: number; failed: number }[] {
  return Array.from({ length: 24 }, (_, i) => {
    const hour = new Date();
    hour.setHours(hour.getHours() - (23 - i));
    return {
      hour: hour.toLocaleTimeString("en-US", { hour: "numeric" }),
      completed: Math.floor(Math.random() * 2000) + 500,
      failed: Math.floor(Math.random() * 50) + 5,
    };
  });
}

// Generate mock APIs
export function generateMockApis(): Api[] {
  return [
    { id: "api_1", name: "orders-api", hosting: "managed", requestsPerMin: 1245, avgLatencyMs: 12, errorRate: 0.2, status: "healthy" },
    { id: "api_2", name: "inventory-api", hosting: "self-hosted", requestsPerMin: 892, avgLatencyMs: 18, errorRate: 0.4, status: "healthy" },
    { id: "api_3", name: "notifications-api", hosting: "managed", requestsPerMin: 2340, avgLatencyMs: 8, errorRate: 0.1, status: "healthy" },
    { id: "api_4", name: "payments-api", hosting: "self-hosted", requestsPerMin: 456, avgLatencyMs: 45, errorRate: 1.8, status: "degraded" },
    { id: "api_5", name: "analytics-api", hosting: "managed", requestsPerMin: 678, avgLatencyMs: 22, errorRate: 0.3, status: "healthy" },
  ];
}
