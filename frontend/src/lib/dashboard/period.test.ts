import { describe, expect, it } from "vitest";

import {
  customPeriod,
  DEFAULT_PRESET,
  formatPeriodParam,
  parsePeriodParam,
  periodEnd,
  periodStart,
  resolvePreset,
} from "./period";

// A fixed Tuesday, so every expectation is a date this file wrote down.
const TODAY = new Date("2026-08-05T10:30:00Z");

describe("resolvePreset", () => {
  it.each([
    ["1d", "2026-08-05", "2026-08-05"],
    ["7d", "2026-07-30", "2026-08-05"],
    ["30d", "2026-07-07", "2026-08-05"],
    ["90d", "2026-05-08", "2026-08-05"],
    ["tm", "2026-08-01", "2026-08-05"],
    ["lm", "2026-07-01", "2026-07-31"],
  ] as const)("%s -> [%s, %s]", (preset, from, to) => {
    expect(resolvePreset(preset, TODAY)).toEqual({ preset, from, to });
  });

  it("last month survives a January", () => {
    const january = new Date("2026-01-15T00:00:00Z");

    expect(resolvePreset("lm", january)).toEqual({
      preset: "lm",
      from: "2025-12-01",
      to: "2025-12-31",
    });
  });

  it("this month on the first is a one-day window", () => {
    const first = new Date("2026-08-01T08:00:00Z");

    expect(resolvePreset("tm", first)).toEqual({
      preset: "tm",
      from: "2026-08-01",
      to: "2026-08-01",
    });
  });

  it("counts in UTC even late in the evening", () => {
    // 23:30 UTC is already tomorrow in Warsaw; the window must not care.
    const evening = new Date("2026-08-05T23:30:00Z");

    expect(resolvePreset("1d", evening).to).toBe("2026-08-05");
  });

  it("defaults to the real clock when no date is injected", () => {
    const period = resolvePreset("1d");

    expect(period.to).toBe(new Date().toISOString().slice(0, 10));
  });
});

describe("customPeriod", () => {
  it("accepts the two clicks in either order", () => {
    expect(customPeriod("2026-07-20", "2026-07-05")).toEqual({
      preset: "custom",
      from: "2026-07-05",
      to: "2026-07-20",
    });
    expect(customPeriod("2026-07-05", "2026-07-20").from).toBe("2026-07-05");
  });
});

describe("parsePeriodParam", () => {
  it("reads a preset id", () => {
    expect(parsePeriodParam("7d", TODAY).preset).toBe("7d");
  });

  it("reads a custom range", () => {
    expect(parsePeriodParam("2026-07-05..2026-07-20", TODAY)).toEqual({
      preset: "custom",
      from: "2026-07-05",
      to: "2026-07-20",
    });
  });

  it("answers the default for garbage rather than an error", () => {
    for (const value of [null, "", "yesterday", "2026-07-05..soon", "07-05..07-20"]) {
      expect(parsePeriodParam(value, TODAY).preset).toBe(DEFAULT_PRESET);
    }
  });
});

describe("formatPeriodParam", () => {
  it("round-trips both forms", () => {
    const preset = resolvePreset("90d", TODAY);
    const custom = customPeriod("2026-07-05", "2026-07-20");

    expect(parsePeriodParam(formatPeriodParam(preset), TODAY)).toEqual(preset);
    expect(parsePeriodParam(formatPeriodParam(custom), TODAY)).toEqual(custom);
  });
});

describe("periodStart and periodEnd", () => {
  it("widen the inclusive dates into whole-day instants", () => {
    // The end reaches the last instant of the last day: cut at its midnight,
    // the window silently drops the day the reader picked.
    const period = customPeriod("2026-07-05", "2026-07-20");

    expect(periodStart(period)).toBe("2026-07-05T00:00:00.000Z");
    expect(periodEnd(period)).toBe("2026-07-20T23:59:59.999Z");
  });
});
