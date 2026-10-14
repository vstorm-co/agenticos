import { describe, expect, it } from "vitest";

import type { UsageStats } from "@/types/stats";

import { bucketLabeller, timelineOf } from "./timeline";

function usage(stepSeconds: number, starts: string[]): UsageStats {
  return {
    timeline: {
      step_seconds: stepSeconds,
      buckets: starts.map((start) => ({ start, runs: 1, completed: 1, cost_usd: "0" })),
    },
  } as UsageStats;
}

describe("the timeline", () => {
  it("reads nothing from a response without one", () => {
    expect(timelineOf(null)).toEqual([]);
    expect(timelineOf({ timeline: null } as UsageStats)).toEqual([]);
  });

  it("names a day step by its UTC day, as the daily series did", () => {
    const daily = usage(86_400, ["2026-10-13T00:00:00Z", "2026-10-14T00:00:00Z"]);

    expect(timelineOf(daily).map(bucketLabeller(daily, "en-GB"))).toEqual(["10-13", "10-14"]);
  });

  it("names a finer step by clock time, and adds the day once it crosses midnight", () => {
    const sameDay = usage(900, ["2026-10-14T12:00:00Z", "2026-10-14T12:15:00Z"]);
    const label = bucketLabeller(sameDay, "en-GB");
    expect(label(timelineOf(sameDay)[0]!)).toMatch(/^\d{2}:\d{2}$/);

    const twoDays = usage(10_800, ["2026-10-13T12:00:00Z", "2026-10-14T12:00:00Z"]);
    expect(bucketLabeller(twoDays, "en-GB")(timelineOf(twoDays)[0]!)).toMatch(/\d{2}\/\d{2}/);
  });

  it("treats a response without a timeline as daily", () => {
    expect(
      bucketLabeller(
        undefined,
        "en",
      )({ start: "2026-10-14T00:00:00Z", runs: 0, completed: 0, cost_usd: "0" }),
    ).toBe("10-14");
  });
});
