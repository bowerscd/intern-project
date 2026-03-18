/**
 * Tests for src/ts/services/liveData.ts
 *
 * Covers the getMealbotSummary transformation: the backend returns a global
 * nested summary and liveData must extract the current user's row to produce
 * per-counterparty balances relative to *that* user.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

describe("liveDataProvider.getMealbotSummary", () => {
  beforeEach(() => {
    (window as any).__API_BASE = "";
    vi.resetModules();

    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** Helper: mock fetch to return different JSON based on the URL path. */
  function mockFetchResponses(summaryData: any, profileData: any) {
    (global.fetch as any).mockImplementation((url: string) => {
      if (url.includes("/mealbot/summary")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(summaryData),
        });
      }
      if (url.includes("/account/profile")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(profileData),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    });
  }

  const PROFILE = {
    id: 1, username: "alice", oidc_email: null,
    email: null, phone: null, phone_provider: "NONE",
    claims: 1, theme: "default", status: "active",
  };

  it("extracts current user's row and computes per-counterparty net", async () => {
    // alice paid for bob 5 times, bob paid for alice 2 times
    // alice paid for carol 1 time, carol paid for alice 3 times
    const globalSummary = {
      alice: {
        bob:   { "incoming-credits": 2, "outgoing-credits": 5 },
        carol: { "incoming-credits": 3, "outgoing-credits": 1 },
      },
      bob: {
        alice: { "incoming-credits": 5, "outgoing-credits": 2 },
        carol: { "incoming-credits": 0, "outgoing-credits": 0 },
      },
      carol: {
        alice: { "incoming-credits": 1, "outgoing-credits": 3 },
        bob:   { "incoming-credits": 0, "outgoing-credits": 0 },
      },
    };
    mockFetchResponses(globalSummary, PROFILE);

    const { liveDataProvider } = await import("../services/liveData");
    const result = await liveDataProvider.getMealbotSummary();

    // alice→bob: outgoing(5) - incoming(2) = +3 (bob owes alice 3)
    // alice→carol: outgoing(1) - incoming(3) = -2 (alice owes carol 2)
    expect(result.balances).toHaveLength(2);
    expect(result.balances[0]).toEqual({ user: "bob", net: 3 });
    expect(result.balances[1]).toEqual({ user: "carol", net: -2 });
  });

  it("returns empty balances when user has no transactions", async () => {
    const globalSummary = {
      alice: {
        bob: { "incoming-credits": 0, "outgoing-credits": 0 },
      },
      bob: {
        alice: { "incoming-credits": 0, "outgoing-credits": 0 },
      },
    };
    mockFetchResponses(globalSummary, PROFILE);

    const { liveDataProvider } = await import("../services/liveData");
    const result = await liveDataProvider.getMealbotSummary();

    expect(result.balances).toHaveLength(1);
    expect(result.balances[0]).toEqual({ user: "bob", net: 0 });
  });

  it("handles user not present in summary (no accounts)", async () => {
    mockFetchResponses({}, PROFILE);

    const { liveDataProvider } = await import("../services/liveData");
    const result = await liveDataProvider.getMealbotSummary();

    expect(result.balances).toEqual([]);
  });

  it("sorts balances descending by net (highest owed first)", async () => {
    const globalSummary = {
      alice: {
        bob:   { "incoming-credits": 0, "outgoing-credits": 1 },
        carol: { "incoming-credits": 0, "outgoing-credits": 10 },
        dave:  { "incoming-credits": 5, "outgoing-credits": 0 },
      },
      bob:   { alice: { "incoming-credits": 1, "outgoing-credits": 0 } },
      carol: { alice: { "incoming-credits": 10, "outgoing-credits": 0 } },
      dave:  { alice: { "incoming-credits": 0, "outgoing-credits": 5 } },
    };
    mockFetchResponses(globalSummary, PROFILE);

    const { liveDataProvider } = await import("../services/liveData");
    const result = await liveDataProvider.getMealbotSummary();

    // carol(+10), bob(+1), dave(-5)
    expect(result.balances.map(b => b.user)).toEqual(["carol", "bob", "dave"]);
    expect(result.balances.map(b => b.net)).toEqual([10, 1, -5]);
  });

  it("does not include other users' global balances", async () => {
    // Regression: old code iterated all users and summed their global totals,
    // showing meaningless numbers unrelated to the logged-in user.
    const globalSummary = {
      alice: {
        bob: { "incoming-credits": 0, "outgoing-credits": 0 },
      },
      bob: {
        alice: { "incoming-credits": 0, "outgoing-credits": 0 },
        carol: { "incoming-credits": 0, "outgoing-credits": 100 },
      },
      carol: {
        bob: { "incoming-credits": 100, "outgoing-credits": 0 },
      },
    };
    mockFetchResponses(globalSummary, PROFILE);

    const { liveDataProvider } = await import("../services/liveData");
    const result = await liveDataProvider.getMealbotSummary();

    // alice should only see bob with net=0, NOT carol or bob's 100-credit balance
    expect(result.balances).toHaveLength(1);
    expect(result.balances[0]).toEqual({ user: "bob", net: 0 });
  });
});
