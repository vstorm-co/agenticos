import { describe, expect, it } from "vitest";

import { dailySpend } from "./spend-series";

const label = (day: Date) => day.toISOString().slice(5, 10);

describe("dailySpend - every day of the window, quiet ones at zero", () => {
  it("fills the days nothing ran on, so a gap reads as a gap", () => {
    const points = dailySpend(
      [
        { day: "2026-10-10", cost_usd: "1.50", run_count: 3 },
        { day: "2026-10-12", cost_usd: "0.25", run_count: 1 },
      ],
      "2026-10-10T08:30:00Z",
      "2026-10-12T20:00:00Z",
      new Date("2026-10-13T00:00:00Z"),
      label,
    );

    expect(points).toEqual([
      { label: "10-10", value: 1.5 },
      { label: "10-11", value: 0 },
      { label: "10-12", value: 0.25 },
    ]);
  });

  it("runs up to now for a window with no end", () => {
    const points = dailySpend(
      [],
      "2026-10-12T00:00:00Z",
      null,
      new Date("2026-10-13T15:00:00Z"),
      label,
    );

    expect(points.map((point) => point.label)).toEqual(["10-12", "10-13"]);
  });
});
