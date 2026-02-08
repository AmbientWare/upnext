import { describe, expect, it, vi } from "vitest";

import { ApiError, getJob, getJobs } from "./conduit-api";

describe("conduit-api", () => {
  it("throws ApiError with status details for non-2xx responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        text: async () => "backend down",
      })
    );

    await expect(getJob("job-1")).rejects.toBeInstanceOf(ApiError);
    await expect(getJob("job-1")).rejects.toMatchObject({
      status: 503,
      statusText: "Service Unavailable",
      message: "backend down",
    });
  });

  it("builds query params for list jobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ jobs: [], total: 0, has_more: false }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await getJobs({ function: "fn.key", status: ["active", "failed"], limit: 20, offset: 10 });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("function=fn.key");
    expect(url).toContain("status=active");
    expect(url).toContain("status=failed");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=10");
  });
});
