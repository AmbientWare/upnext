import { describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getJob,
  getJobs,
  verifyAuth,
  getAdminUsers,
  createAdminUser,
  deleteAdminUser,
  updateAdminUser,
  getAdminUserApiKeys,
  createAdminApiKey,
  deleteAdminApiKey,
  toggleAdminApiKey,
  rotateAdminApiKey,
  queryKeys,
} from "./upnext-api";

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

describe("auth api", () => {
  it("verifyAuth sends POST to /auth/verify", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, user: { id: "u1", username: "admin", is_admin: true } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await verifyAuth();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/auth/verify");
    expect(init.method).toBe("POST");
    expect(result.ok).toBe(true);
  });
});

describe("admin api", () => {
  it("getAdminUsers fetches user list", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ users: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getAdminUsers();
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("/admin/users");
    expect(result.users).toEqual([]);
  });

  it("createAdminUser sends POST with body and returns api_key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "u1",
        username: "newuser",
        is_admin: false,
        api_key: { id: "k1", raw_key: "upnxt_abc" },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createAdminUser({ username: "newuser", is_admin: false });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/users");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ username: "newuser", is_admin: false });
    expect(result.api_key.raw_key).toBe("upnxt_abc");
  });

  it("deleteAdminUser sends DELETE", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await deleteAdminUser("u1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/users/u1");
    expect(init.method).toBe("DELETE");
  });

  it("deleteAdminUser throws on error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
        text: async () => "not found",
      })
    );

    await expect(deleteAdminUser("u1")).rejects.toBeInstanceOf(ApiError);
  });

  it("updateAdminUser sends PATCH with body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "u1", username: "user", is_admin: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await updateAdminUser("u1", { is_admin: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/users/u1");
    expect(init.method).toBe("PATCH");
  });

  it("getAdminUserApiKeys fetches keys for user", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ api_keys: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getAdminUserApiKeys("u1");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("/admin/users/u1/api-keys");
    expect(result.api_keys).toEqual([]);
  });

  it("createAdminApiKey sends POST with name", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "k1", name: "my-key", raw_key: "upnxt_abc123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createAdminApiKey("u1", { name: "my-key" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/users/u1/api-keys");
    expect(init.method).toBe("POST");
    expect(result.raw_key).toBe("upnxt_abc123");
  });

  it("deleteAdminApiKey sends DELETE", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await deleteAdminApiKey("u1", "k1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/users/u1/api-keys/k1");
    expect(init.method).toBe("DELETE");
  });

  it("toggleAdminApiKey sends PATCH with is_active", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "k1", is_active: false }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await toggleAdminApiKey("u1", "k1", { is_active: false });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/users/u1/api-keys/k1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ is_active: false });
  });

  it("rotateAdminApiKey sends POST to rotate endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "k2", raw_key: "upnxt_rotated" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await rotateAdminApiKey("u1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/users/u1/rotate-api-key");
    expect(init.method).toBe("POST");
    expect(result.raw_key).toBe("upnxt_rotated");
  });
});

describe("queryKeys", () => {
  it("produces stable admin query keys", () => {
    expect(queryKeys.adminUsers).toEqual(["admin", "users"]);
    expect(queryKeys.adminUserApiKeys("u1")).toEqual(["admin", "users", "u1", "api-keys"]);
  });
});
