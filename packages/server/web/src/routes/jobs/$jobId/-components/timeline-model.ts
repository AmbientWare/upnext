import type { Job } from "@/lib/types";

export interface TreeJob extends Job {
  depth: number;
  parentId: string | null;
  rootId: string;
}

export interface TimelineDomain {
  min: number;
  max: number;
  span: number;
}

interface TimelineDomainOptions {
  live?: boolean;
}

export interface TimelineTick {
  ms: number;
  at: number;
  label: string;
}

export function getParentId(job: Job): string | null {
  return job.parent_id ?? null;
}

export function getRootId(job: Job): string {
  return job.root_id;
}

function getSortTime(job: Job): number {
  const value = job.started_at ?? job.created_at ?? job.scheduled_at ?? job.completed_at;
  if (!value) return Number.MAX_SAFE_INTEGER;
  const ts = new Date(value).getTime();
  return Number.isFinite(ts) ? ts : Number.MAX_SAFE_INTEGER;
}

export function buildJobTree(jobs: Job[], rootJobId: string): TreeJob[] {
  const byId = new Map(jobs.map((job) => [job.id, job]));
  const root = byId.get(rootJobId);
  if (!root) return [];

  const sortedJobs = [...jobs].sort((a, b) => getSortTime(a) - getSortTime(b));
  const childrenById = new Map<string, string[]>();
  for (const job of jobs) childrenById.set(job.id, []);

  for (const job of sortedJobs) {
    if (job.id === rootJobId) continue;
    const parentId = getParentId(job);
    const attachParentId =
      parentId && byId.has(parentId) ? parentId : rootJobId;
    childrenById.get(attachParentId)?.push(job.id);
  }

  const ordered: TreeJob[] = [];
  const visited = new Set<string>();

  const walk = (jobId: string, depth: number) => {
    const job = byId.get(jobId);
    if (!job || visited.has(jobId)) return;
    visited.add(jobId);
    ordered.push({
      ...job,
      depth,
      parentId: getParentId(job),
      rootId: getRootId(job),
    });
    const childIds = childrenById.get(jobId) ?? [];
    for (const childId of childIds) walk(childId, depth + 1);
  };

  walk(rootJobId, 0);

  for (const job of sortedJobs) {
    if (!visited.has(job.id)) {
      walk(job.id, 1);
    }
  }

  return ordered;
}

export function getTimelineDomain(jobs: Job[]) {
  const now = Date.now();
  return getTimelineDomainAt(jobs, now);
}

export function getTimelineDomainAt(
  jobs: Job[],
  nowMs: number,
  options: TimelineDomainOptions = {}
): TimelineDomain {
  const now = Number.isFinite(nowMs) ? nowMs : Date.now();
  const starts = jobs
    .map((job) => job.started_at ?? job.created_at ?? job.scheduled_at)
    .filter((value): value is string => !!value)
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value));

  const ends = jobs
    .map((job) => {
      if (job.completed_at) return new Date(job.completed_at).getTime();
      if (job.started_at || job.created_at || job.scheduled_at) return now;
      return NaN;
    })
    .filter((value) => Number.isFinite(value));

  const min = starts.length ? Math.min(...starts) : now;
  const rawMax = ends.length ? Math.max(...ends) : now;

  let max = rawMax;
  if (options.live) {
    const baseSpan = Math.max(rawMax - min, 1);
    // Keep the right edge slightly ahead of "now" so active bars can visibly grow.
    const rightPadMs = Math.max(baseSpan * 0.08, 1500);
    max = Math.max(rawMax, now) + rightPadMs;
  }

  const span = Math.max(max - min, 1);
  return { min, max, span };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function getBarPosition(
  job: Job,
  domain: TimelineDomain,
  nowMs: number
) {
  const startRaw = job.started_at ?? job.created_at ?? job.scheduled_at;
  if (!startRaw) return { left: 0, width: 1 };
  const start = new Date(startRaw).getTime();
  const end = job.completed_at
    ? new Date(job.completed_at).getTime()
    : nowMs;

  const rawStart = Number.isFinite(start) ? start : domain.min;
  const rawEnd = Number.isFinite(end) ? end : rawStart;

  const safeStart = clamp(rawStart, domain.min, domain.max);
  const safeEnd = clamp(Math.max(rawEnd, safeStart), domain.min, domain.max);

  const left = ((safeStart - domain.min) / domain.span) * 100;
  const rawWidth = ((safeEnd - safeStart) / domain.span) * 100;
  const maxWidth = Math.max(100 - left, 0);
  const width =
    rawWidth <= 0 ? Math.min(0.6, maxWidth) : Math.min(maxWidth, Math.max(rawWidth, 0.6));

  return { left: Math.max(0, left), width: Math.max(0, width) };
}

const NICE_TICK_STEPS_MS = [
  1000,
  2000,
  5000,
  10000,
  15000,
  30000,
  60000,
  120000,
  300000,
  600000,
  900000,
  1800000,
  3600000,
  7200000,
  10800000,
];

function chooseTickStep(spanMs: number, targetCount: number): number {
  for (const step of NICE_TICK_STEPS_MS) {
    if (spanMs / step <= targetCount) return step;
  }
  // Fallback to a coarse step if the range is very large.
  const rough = Math.ceil(spanMs / targetCount);
  const hour = 3600000;
  return Math.ceil(rough / hour) * hour;
}

function formatTickLabel(ms: number): string {
  return new Date(ms).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function buildTimelineTicks(domain: TimelineDomain, targetCount = 6): TimelineTick[] {
  const step = chooseTickStep(domain.span, Math.max(targetCount, 2));
  const start = Math.floor(domain.min / step) * step;
  const ticks: TimelineTick[] = [];

  for (let tickMs = start; tickMs <= domain.max; tickMs += step) {
    if (tickMs < domain.min) continue;
    const at = clamp((tickMs - domain.min) / domain.span, 0, 1);
    ticks.push({
      ms: tickMs,
      at,
      label: formatTickLabel(tickMs),
    });
  }

  if (ticks.length === 0) {
    ticks.push({
      ms: domain.min,
      at: 0,
      label: formatTickLabel(domain.min),
    });
  }

  return ticks;
}
