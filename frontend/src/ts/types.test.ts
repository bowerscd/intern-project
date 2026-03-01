/**
 * Tests for src/ts/types.ts
 *
 * Covers: ClaimFlags, decodeClaims, encodeClaims.
 */

import { describe, it, expect } from "vitest";
import { ClaimFlags, decodeClaims, encodeClaims } from "./types";

describe("ClaimFlags", () => {
  it("defines expected claim values as powers of 2", () => {
    expect(ClaimFlags.BASIC).toBe(1);
    expect(ClaimFlags.ADMIN).toBe(2);
    expect(ClaimFlags.MEALBOT).toBe(4);
    expect(ClaimFlags.COOKBOOK).toBe(8);
    expect(ClaimFlags.HAPPY_HOUR).toBe(16);
    expect(ClaimFlags.HAPPY_HOUR_TYRANT).toBe(32);
  });

  it("all flags are unique powers of 2", () => {
    const values = Object.values(ClaimFlags);
    values.forEach((v) => {
      expect(v).toBeGreaterThan(0);
      expect(v & (v - 1)).toBe(0); // power of 2 check
    });
    // No duplicates
    expect(new Set(values).size).toBe(values.length);
  });
});

describe("decodeClaims", () => {
  it("decodes single claim", () => {
    expect(decodeClaims(1)).toEqual(["BASIC"]);
    expect(decodeClaims(2)).toEqual(["ADMIN"]);
  });

  it("decodes multiple claims", () => {
    const result = decodeClaims(1 | 4 | 16); // BASIC + MEALBOT + HAPPY_HOUR
    expect(result).toContain("BASIC");
    expect(result).toContain("MEALBOT");
    expect(result).toContain("HAPPY_HOUR");
    expect(result).toHaveLength(3);
  });

  it("decodes all claims", () => {
    const allBits = 1 | 2 | 4 | 8 | 16 | 32;
    const result = decodeClaims(allBits);
    expect(result).toHaveLength(6);
  });

  it("returns empty array for 0", () => {
    expect(decodeClaims(0)).toEqual([]);
  });
});

describe("encodeClaims", () => {
  it("encodes single claim", () => {
    expect(encodeClaims(["BASIC"])).toBe(1);
  });

  it("encodes multiple claims", () => {
    expect(encodeClaims(["BASIC", "MEALBOT"])).toBe(1 | 4);
  });

  it("returns 0 for empty array", () => {
    expect(encodeClaims([])).toBe(0);
  });

  it("ignores unknown claim names", () => {
    expect(encodeClaims(["BASIC", "UNKNOWN"])).toBe(1);
  });

  it("roundtrips with decodeClaims", () => {
    const original = ["BASIC", "ADMIN", "HAPPY_HOUR"];
    const encoded = encodeClaims(original);
    const decoded = decodeClaims(encoded);
    expect(decoded.sort()).toEqual(original.sort());
  });
});
