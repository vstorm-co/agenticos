import { describe, expect, it } from "vitest";

import { axisTicks, type PassRatePoint, type Row } from "./pass-rate-lines.impl";

function row(index: number, tick: string): Row {
  const point: PassRatePoint = {
    index,
    rate: 0.5,
    tick,
    draft: false,
    color: "var(--color-muted-foreground)",
    href: `/agents/a/evals/r${index}`,
    title: "v1",
    details: [],
  };
  return { index, tick, point, refunds: 0.5 };
}

describe("axisTicks", () => {
  it("names each day once, at its first run, and each time today", () => {
    const { ticks, label } = axisTicks([
      row(0, "Oct 14"),
      row(1, "Oct 14"),
      row(2, "Oct 15"),
      row(3, "08:41"),
      row(4, "08:41"),
      row(5, "09:02"),
    ]);

    expect(ticks).toEqual([0, 2, 3, 5]);
    const names = ticks.map((index) => label.get(index));
    expect(names).toEqual(["Oct 14", "Oct 15", "08:41", "09:02"]);
    expect(new Set(names).size).toBe(names.length);
  });

  it("has nothing to name without runs", () => {
    expect(axisTicks([])).toEqual({ ticks: [], label: new Map() });
  });
});
