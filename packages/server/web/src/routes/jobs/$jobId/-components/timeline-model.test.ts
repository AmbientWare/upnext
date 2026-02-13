import { describe, expect, it } from "vitest";

import type { Job } from "@/lib/types";
import {
  buildJobTree,
  getBarPosition,
  getTimelineDomainAt,
} from "./timeline-model";

function mkJob(partial: Partial<Job> & Pick<Job, "id">): Job {
  return {
    id: partial.id,
    function: partial.function ?? "fn",
    function_name: partial.function_name ?? "fn",
    job_type: partial.job_type ?? "task",
    source: partial.source ?? { type: "task" },
    status: partial.status ?? "active",
    created_at: partial.created_at ?? "2026-02-08T00:00:00Z",
    scheduled_at: partial.scheduled_at ?? null,
    started_at: partial.started_at ?? partial.created_at ?? null,
    completed_at: partial.completed_at ?? null,
    attempts: partial.attempts ?? 1,
    max_retries: partial.max_retries ?? 0,
    timeout: partial.timeout ?? null,
    worker_id: partial.worker_id ?? null,
    parent_id: partial.parent_id ?? null,
    root_id: partial.root_id ?? partial.id,
    progress: partial.progress ?? 0,
    kwargs: partial.kwargs ?? {},
    checkpoint: partial.checkpoint ?? null,
    checkpoint_at: partial.checkpoint_at ?? null,
    dlq_replayed_from: partial.dlq_replayed_from ?? null,
    dlq_failed_at: partial.dlq_failed_at ?? null,
    result: partial.result ?? null,
    error: partial.error ?? null,
    duration_ms: partial.duration_ms ?? null,
  };
}

describe("timeline-model", () => {
  it("builds a nested tree and attaches missing-parent jobs under root", () => {
    const root = mkJob({ id: "root", root_id: "root", started_at: "2026-02-08T10:00:00Z" });
    const child = mkJob({
      id: "child",
      parent_id: "root",
      root_id: "root",
      started_at: "2026-02-08T10:00:01Z",
    });
    const orphan = mkJob({
      id: "orphan",
      parent_id: "missing",
      root_id: "root",
      started_at: "2026-02-08T10:00:02Z",
    });

    const tree = buildJobTree([orphan, child, root], "root");
    expect(tree.map((j) => [j.id, j.depth])).toEqual([
      ["root", 0],
      ["child", 1],
      ["orphan", 1],
    ]);
  });

  it("computes live domain with right padding", () => {
    const jobs = [
      mkJob({
        id: "j1",
        started_at: "2026-02-08T10:00:00.000Z",
        completed_at: "2026-02-08T10:00:10.000Z",
      }),
    ];
    const domain = getTimelineDomainAt(jobs, Date.parse("2026-02-08T10:00:11.000Z"), {
      live: true,
    });

    expect(domain.min).toBe(Date.parse("2026-02-08T10:00:00.000Z"));
    expect(domain.max).toBeGreaterThan(Date.parse("2026-02-08T10:00:11.000Z"));
    expect(domain.span).toBe(domain.max - domain.min);
  });

  it("clamps bar positions and keeps minimum visible width", () => {
    const domain = {
      min: Date.parse("2026-02-08T10:00:00.000Z"),
      max: Date.parse("2026-02-08T10:01:40.000Z"),
      span: 100000,
    };

    const completed = mkJob({
      id: "done",
      started_at: "2026-02-08T10:00:10.000Z",
      completed_at: "2026-02-08T10:00:30.000Z",
    });
    const active = mkJob({
      id: "active",
      started_at: "2026-02-08T10:01:39.900Z",
      completed_at: null,
    });

    const completedBar = getBarPosition(completed, domain, Date.parse("2026-02-08T10:01:00.000Z"));
    const activeBar = getBarPosition(active, domain, Date.parse("2026-02-08T10:01:40.000Z"));

    expect(completedBar.left).toBeGreaterThanOrEqual(0);
    expect(completedBar.width).toBeGreaterThan(0);
    expect(activeBar.width).toBeGreaterThan(0);
    expect(activeBar.left + activeBar.width).toBeLessThanOrEqual(100);
  });

  it("handles large timeline trees within a practical budget", () => {
    const root = mkJob({ id: "root", root_id: "root", started_at: "2026-02-08T10:00:00Z" });
    const jobs: Job[] = [root];
    for (let i = 1; i <= 1500; i += 1) {
      jobs.push(
        mkJob({
          id: `job-${i}`,
          parent_id: i === 1 ? "root" : `job-${i - 1}`,
          root_id: "root",
          started_at: `2026-02-08T10:00:${String(i % 60).padStart(2, "0")}Z`,
        })
      );
    }

    const start = performance.now();
    const tree = buildJobTree(jobs, "root");
    const elapsedMs = performance.now() - start;

    expect(tree).toHaveLength(1501);
    expect(elapsedMs).toBeLessThan(2000);
  });
});
