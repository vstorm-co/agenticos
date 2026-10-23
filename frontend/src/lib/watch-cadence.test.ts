import { describe, expect, it } from "vitest";

import { WATCH_INTERVALS, allowedIntervals, cadenceLabel } from "./watch-cadence";

const t = (key: string, values?: Record<string, number>) =>
  values ? `${key}:${values.count}` : key;

describe("a watch's cadence", () => {
  it("names minutes, hours, a day and a week", () => {
    expect(WATCH_INTERVALS.map((minutes) => cadenceLabel(minutes, t))).toEqual([
      "everyMinutes:15",
      "everyMinutes:30",
      "everyHours:1",
      "everyHours:3",
      "everyHours:6",
      "everyHours:12",
      "daily",
      "weekly",
    ]);
  });

  it("offers only what the organization's floor allows, never under fifteen minutes", () => {
    expect(allowedIntervals(60)).toEqual([60, 180, 360, 720, 1440, 10080]);
    expect(allowedIntervals(0)[0]).toBe(15);
  });
});
