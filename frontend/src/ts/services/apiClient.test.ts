/**
 * Tests for src/ts/services/apiClient.ts
 *
 * Covers: qualifyRedirect, loginUrl, registerUrl, and fetch-based API calls.
 * Uses a mock fetch to avoid real network requests.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Set up window.__API_BASE before importing the module
const originalApiBase = (window as any).__API_BASE;

describe("apiClient — proxy mode (API_BASE = '')", () => {
  beforeEach(() => {
    (window as any).__API_BASE = "";
    // Reset module cache so the module re-reads __API_BASE
    vi.resetModules();
  });

  afterEach(() => {
    (window as any).__API_BASE = originalApiBase;
    vi.restoreAllMocks();
  });

  it("loginUrl uses relative path in proxy mode", async () => {
    const mod = await import("../services/apiClient");
    const url = mod.loginUrl("google", "/account");
    expect(url).toBe("/api/v2/auth/login/google?redirect=%2Faccount");
  });

  it("registerUrl uses relative path in proxy mode", async () => {
    const mod = await import("../services/apiClient");
    const url = mod.registerUrl("test", "/auth/complete-registration");
    expect(url).toBe(
      "/api/v2/auth/register/test?redirect=%2Fauth%2Fcomplete-registration"
    );
  });

  it("loginUrl without redirect omits param", async () => {
    const mod = await import("../services/apiClient");
    const url = mod.loginUrl("google");
    expect(url).toBe("/api/v2/auth/login/google?");
  });
});

describe("apiClient — direct mode (API_BASE = absolute URL)", () => {
  beforeEach(() => {
    (window as any).__API_BASE = "http://api.example.com:8000";
    vi.resetModules();
  });

  afterEach(() => {
    (window as any).__API_BASE = originalApiBase;
    vi.restoreAllMocks();
  });

  it("loginUrl qualifies redirect with frontend origin", async () => {
    const mod = await import("../services/apiClient");
    const url = mod.loginUrl("google", "/account");
    // Should prefix the redirect with window.location.origin
    expect(url).toContain("api.example.com");
    expect(url).toContain("redirect=");
    // The redirect param should contain the frontend origin
    const params = new URLSearchParams(url.split("?")[1]);
    const redirect = params.get("redirect")!;
    expect(redirect).toContain("http://localhost"); // jsdom default origin
    expect(redirect).toContain("/account");
  });

  it("registerUrl qualifies redirect in direct mode", async () => {
    const mod = await import("../services/apiClient");
    const url = mod.registerUrl("test", "/complete");
    const params = new URLSearchParams(url.split("?")[1]);
    const redirect = params.get("redirect")!;
    expect(redirect).toContain("http://localhost");
    expect(redirect).toContain("/complete");
  });
});

describe("apiClient — fetch requests", () => {
  beforeEach(() => {
    (window as any).__API_BASE = "";
    vi.resetModules();
    // Mock global fetch
    global.fetch = vi.fn();
  });

  afterEach(() => {
    (window as any).__API_BASE = originalApiBase;
    vi.restoreAllMocks();
  });

  it("getProfile calls /api/v2/account/profile with credentials", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: 1, username: "alice" }),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    const profile = await mod.getProfile();
    expect(profile.username).toBe("alice");

    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe("/api/v2/account/profile");
    expect(opts.credentials).toBe("include");
    expect(opts.method).toBe("GET");
  });

  it("completeRegistration sends POST with JSON body and CSRF token", async () => {
    // First call: CSRF token fetch, second call: the actual POST
    const csrfResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ csrf_token: "test-csrf-token" }),
    };
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: 1, username: "newuser" }),
    };
    (global.fetch as any)
      .mockResolvedValueOnce(csrfResponse)
      .mockResolvedValueOnce(mockResponse);

    const mod = await import("../services/apiClient");
    const result = await mod.completeRegistration({ username: "newuser" });
    expect(result.username).toBe("newuser");

    // Second call is the actual POST
    const [url, opts] = (global.fetch as any).mock.calls[1];
    expect(url).toBe("/api/v2/auth/complete-registration");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ username: "newuser" });
    expect(opts.headers["X-CSRF-Token"]).toBe("test-csrf-token");
  });

  it("throws on non-ok response", async () => {
    const mockResponse = {
      ok: false,
      status: 401,
      text: () => Promise.resolve("Unauthorized"),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    await expect(mod.getProfile()).rejects.toThrow("401");
  });

  it("returns undefined for 204 No Content", async () => {
    const mockResponse = {
      ok: true,
      status: 204,
      json: () => Promise.reject(new Error("no body")),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    // getProfile returns undefined on 204
    const result = await mod.getProfile();
    expect(result).toBeUndefined();
  });

  it("getMealbotLedger fetches all pages via pagination", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 100 }),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    await mod.getMealbotLedger();

    const [url] = (global.fetch as any).mock.calls[0];
    expect(url).toBe("/api/v2/mealbot/ledger?page=1&page_size=100");
  });

  it("getMealbotSummary builds query string from params", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    await mod.getMealbotSummary("alice", "2025-01-01", "2025-12-31");

    const [url] = (global.fetch as any).mock.calls[0];
    expect(url).toContain("user=alice");
    expect(url).toContain("start=2025-01-01");
    expect(url).toContain("end=2025-12-31");
  });

  it("all GET requests include Content-Type: application/json", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    await mod.getProfile();

    const [, opts] = (global.fetch as any).mock.calls[0];
    expect(opts.headers["Content-Type"]).toBe("application/json");
  });
});

describe("apiClient — admin account management", () => {
  beforeEach(() => {
    (window as any).__API_BASE = "";
    vi.resetModules();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    (window as any).__API_BASE = originalApiBase;
    vi.restoreAllMocks();
  });

  it("getAdminAccounts fetches /api/v2/account/admin/accounts", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: 1, username: "alice", status: "active" }]),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    const result = await mod.getAdminAccounts();

    const [url] = (global.fetch as any).mock.calls[0];
    expect(url).toBe("/api/v2/account/admin/accounts");
    expect(result).toHaveLength(1);
    expect(result[0].username).toBe("alice");
  });

  it("getAdminAccounts with status filter appends query param", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    await mod.getAdminAccounts("pending_approval");

    const [url] = (global.fetch as any).mock.calls[0];
    expect(url).toContain("status_filter=pending_approval");
  });

  it("updateAccountStatus sends POST with status body", async () => {
    const csrfResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ csrf_token: "csrf-tok" }),
    };
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: 5, username: "bob", status: "active" }),
    };
    (global.fetch as any)
      .mockResolvedValueOnce(csrfResponse)
      .mockResolvedValueOnce(mockResponse);

    const mod = await import("../services/apiClient");
    const result = await mod.updateAccountStatus(5, { status: "active" });

    expect(result.status).toBe("active");
    const [url, opts] = (global.fetch as any).mock.calls[1];
    expect(url).toBe("/api/v2/account/admin/accounts/5/status");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ status: "active" });
  });

  it("updateAccountRole sends POST with grant_admin body", async () => {
    const csrfResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ csrf_token: "csrf-tok" }),
    };
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: 3, username: "carol", claims: 3 }),
    };
    (global.fetch as any)
      .mockResolvedValueOnce(csrfResponse)
      .mockResolvedValueOnce(mockResponse);

    const mod = await import("../services/apiClient");
    const result = await mod.updateAccountRole(3, { grant_admin: true });

    expect(result.claims).toBe(3);
    const [url, opts] = (global.fetch as any).mock.calls[1];
    expect(url).toBe("/api/v2/account/admin/accounts/3/role");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ grant_admin: true });
  });

  it("completeRegistration response includes status field", async () => {
    const csrfResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ csrf_token: "csrf-tok" }),
    };
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: 1, username: "newuser", status: "pending_approval", message: "Awaiting approval." }),
    };
    (global.fetch as any)
      .mockResolvedValueOnce(csrfResponse)
      .mockResolvedValueOnce(mockResponse);

    const mod = await import("../services/apiClient");
    const result = await mod.completeRegistration({ username: "newuser" });
    expect(result.status).toBe("pending_approval");
    expect(result.message).toBe("Awaiting approval.");
  });
});
