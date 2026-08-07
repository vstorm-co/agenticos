import { describe, expect, it } from "vitest";

import { addMonths, inRange, isSameOrAfterMonth, monthGrid, yearMonthOf } from "./calendar";

describe("monthGrid", () => {
  it("is always 42 cells, Monday-first", () => {
    // July 2026 starts on a Wednesday: two leading out-of-month days.
    const cells = monthGrid({ year: 2026, month: 7 });

    expect(cells).toHaveLength(42);
    expect(cells[0]).toEqual({ date: "2026-06-29", inMonth: false });
    expect(cells[2]).toEqual({ date: "2026-07-01", inMonth: true });
    expect(cells[32]).toEqual({ date: "2026-07-31", inMonth: true });
    expect(cells[33]).toEqual({ date: "2026-08-01", inMonth: false });
  });

  it("a month starting on Monday leads with no padding", () => {
    // June 2026 starts on a Monday.
    const cells = monthGrid({ year: 2026, month: 6 });

    expect(cells[0]).toEqual({ date: "2026-06-01", inMonth: true });
  });

  it("February in a leap year keeps its 29th", () => {
    const cells = monthGrid({ year: 2028, month: 2 });

    expect(cells.filter((cell) => cell.inMonth)).toHaveLength(29);
  });
});

describe("addMonths", () => {
  it("walks across year boundaries in both directions", () => {
    expect(addMonths({ year: 2026, month: 12 }, 1)).toEqual({ year: 2027, month: 1 });
    expect(addMonths({ year: 2026, month: 1 }, -1)).toEqual({ year: 2025, month: 12 });
    expect(addMonths({ year: 2026, month: 7 }, 0)).toEqual({ year: 2026, month: 7 });
  });
});

describe("yearMonthOf and month ordering", () => {
  it("reads a month out of an ISO date", () => {
    expect(yearMonthOf("2026-08-05")).toEqual({ year: 2026, month: 8 });
  });

  it("orders months across years", () => {
    const august = { year: 2026, month: 8 };

    expect(isSameOrAfterMonth(august, august)).toBe(true);
    expect(isSameOrAfterMonth({ year: 2026, month: 9 }, august)).toBe(true);
    expect(isSameOrAfterMonth({ year: 2027, month: 1 }, august)).toBe(true);
    expect(isSameOrAfterMonth({ year: 2026, month: 7 }, august)).toBe(false);
    expect(isSameOrAfterMonth({ year: 2025, month: 12 }, august)).toBe(false);
  });
});

describe("inRange", () => {
  it("is inclusive on both ends", () => {
    expect(inRange("2026-07-05", "2026-07-05", "2026-07-20")).toBe(true);
    expect(inRange("2026-07-20", "2026-07-05", "2026-07-20")).toBe(true);
    expect(inRange("2026-07-21", "2026-07-05", "2026-07-20")).toBe(false);
    expect(inRange("2026-07-04", "2026-07-05", "2026-07-20")).toBe(false);
  });
});
