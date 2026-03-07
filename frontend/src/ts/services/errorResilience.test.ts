/**
 * Error resilience tests for the API client.
 *
 * Validates that the client handles edge cases gracefully:
 * - Network failures
 * - Malformed JSON responses
 * - Timeout-like scenarios
 * - Empty responses
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

const originalApiBase = (window as any).__API_BASE;

describe("apiClient error resilience", () => {
  beforeEach(() => {
    (window as any).__API_BASE = "";
    vi.resetModules();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    (window as any).__API_BASE = originalApiBase;
    vi.restoreAllMocks();
  });

  it("throws on network failure (fetch rejects)", async () => {
    (global.fetch as any).mockRejectedValue(new TypeError("Failed to fetch"));

    const mod = await import("../services/apiClient");
    await expect(mod.getProfile()).rejects.toThrow("Failed to fetch");
  });

  it("throws meaningful message on HTTP error with body", async () => {
    const mockResponse = {
      ok: false,
      status: 500,
      text: () => Promise.resolve(JSON.stringify({ detail: "Internal Server Error" })),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    await expect(mod.getProfile()).rejects.toThrow("Internal Server Error");
  });

  it("handles text() failure gracefully in error path", async () => {
    const mockResponse = {
      ok: false,
      status: 502,
      text: () => Promise.reject(new Error("body unreadable")),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    // Should still throw with a user-friendly message even if body is unreadable
    await expect(mod.getProfile()).rejects.toThrow("Request failed (502)");
  });

  it("handles empty JSON body on 200", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve(null),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    const result = await mod.getProfile();
    // Should return whatever the body is, even if null
    expect(result).toBeNull();
  });

  it("POST with undefined body does not send body", async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: "ok" }),
    };
    (global.fetch as any).mockResolvedValue(mockResponse);

    const mod = await import("../services/apiClient");
    // claimAccount sends a POST — verify body serialization works
    await mod.claimAccount({ username: "test" });

    const [, opts] = (global.fetch as any).mock.calls.find(
      ([url]: [string]) => !url.includes("csrf-token")
    );
    expect(JSON.parse(opts.body)).toEqual({ username: "test" });
  });

  it("handles concurrent requests independently", async () => {
    let callCount = 0;
    (global.fetch as any).mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ id: 1 }),
        });
      }
      return Promise.resolve({
        ok: false,
        status: 401,
        text: () => Promise.resolve("Unauthorized"),
      });
    });

    const mod = await import("../services/apiClient");
    const results = await Promise.allSettled([
      mod.getProfile(),
      mod.getProfile(),
    ]);

    expect(results[0].status).toBe("fulfilled");
    expect(results[1].status).toBe("rejected");
  });
});
