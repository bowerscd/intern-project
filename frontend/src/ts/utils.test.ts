/**
 * Tests for src/ts/utils.ts
 *
 * Covers: byId, esc, table, status, formatDate, formatDateShort,
 * setupInfiniteScroll, appendTableRows.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { byId, esc, table, status, formatDate, formatDateShort, appendTableRows } from "./utils";

describe("esc", () => {
  it("escapes HTML special characters", () => {
    expect(esc('<script>alert("xss")</script>')).toBe(
      "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"
    );
  });

  it("escapes ampersands", () => {
    expect(esc("a & b")).toBe("a &amp; b");
  });

  it("returns empty string for empty input", () => {
    expect(esc("")).toBe("");
  });

  it("leaves safe strings unchanged", () => {
    expect(esc("hello world 123")).toBe("hello world 123");
  });
});

describe("byId", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="test-el">content</div>';
  });

  it("returns the element when it exists", () => {
    const el = byId<HTMLDivElement>("test-el");
    expect(el).toBeInstanceOf(HTMLDivElement);
    expect(el.textContent).toBe("content");
  });

  it("throws when element is missing", () => {
    expect(() => byId("nonexistent")).toThrow("Missing element: nonexistent");
  });
});

describe("table", () => {
  it("generates correct HTML table", () => {
    const html = table(["Name", "Age"], [["Alice", "30"], ["Bob", "25"]]);
    expect(html).toContain("<thead>");
    expect(html).toContain("<th>Name</th>");
    expect(html).toContain("<th>Age</th>");
    expect(html).toContain("<td>Alice</td>");
    expect(html).toContain("<td>30</td>");
    expect(html).toContain("<td>Bob</td>");
  });

  it("escapes cell content", () => {
    const html = table(["Col"], [['<img src=x onerror="alert(1)">']]);
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("handles empty rows", () => {
    const html = table(["H1"], []);
    expect(html).toContain("<thead>");
    expect(html).toContain("<tbody></tbody>");
  });
});

describe("status", () => {
  it("wraps message in a status div", () => {
    const html = status("Loading...");
    expect(html).toBe('<div class="status">Loading...</div>');
  });
});

describe("formatDate", () => {
  it("returns TBD for empty string", () => {
    expect(formatDate("")).toBe("TBD");
  });

  it("returns TBD for invalid date", () => {
    expect(formatDate("not-a-date")).toBe("TBD");
  });

  it("formats a valid ISO date string", () => {
    const result = formatDate("2025-01-15T12:00:00Z");
    // Should produce a locale-formatted string (not TBD)
    expect(result).not.toBe("TBD");
    expect(result).toContain("2025");
  });
});

describe("formatDateShort", () => {
  it("returns TBD for empty string", () => {
    expect(formatDateShort("")).toBe("TBD");
  });

  it("returns TBD for invalid date", () => {
    expect(formatDateShort("garbage")).toBe("TBD");
  });

  it("formats a valid date to short form", () => {
    const result = formatDateShort("2025-06-15T00:00:00Z");
    expect(result).not.toBe("TBD");
    expect(result).toContain("2025");
  });
});

describe("appendTableRows", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table id="test-table">
        <thead><tr><th>A</th><th>B</th></tr></thead>
        <tbody></tbody>
      </table>
    `;
  });

  it("appends rows to existing table body", () => {
    appendTableRows("test-table", [["r1a", "r1b"], ["r2a", "r2b"]]);
    const tbody = document.querySelector("#test-table tbody")!;
    expect(tbody.querySelectorAll("tr").length).toBe(2);
    expect(tbody.textContent).toContain("r1a");
    expect(tbody.textContent).toContain("r2b");
  });

  it("escapes appended content", () => {
    appendTableRows("test-table", [["<b>xss</b>", "safe"]]);
    const tbody = document.querySelector("#test-table tbody")!;
    expect(tbody.innerHTML).toContain("&lt;b&gt;");
    expect(tbody.innerHTML).not.toContain("<b>xss</b>");
  });

  it("does nothing for nonexistent table", () => {
    // Should not throw
    appendTableRows("nonexistent", [["a", "b"]]);
  });
});
