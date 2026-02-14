import { describe, expect, it, vi } from "vitest";

import { ApiError, getJob, getJobs } from "./upnext-api";

describe("upnext-api", () => {
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

    await getJobs({ function: "fn.key", status: ["active", "failed"], limit: 20, cursor: "job-abc" });

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("function=fn.key");
    expect(url).toContain("status=active");
    expect(url).toContain("status=failed");
    expect(url).toContain("limit=20");
    expect(url).toContain("cursor=job-abc");
  });

  it("throws timeout ApiError when request exceeds timeout", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        () =>
          new Promise((_resolve, reject) => {
            setTimeout(() => {
              reject(new DOMException("aborted", "AbortError"));
            }, 0);
          })
      )
    );

    await expect(getJob("job-timeout")).rejects.toBeInstanceOf(ApiError);
    await expect(getJob("job-timeout")).rejects.toMatchObject({
      status: 408,
      statusText: "Request Timeout",
    });
  });
});
