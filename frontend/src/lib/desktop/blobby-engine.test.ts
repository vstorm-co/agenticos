import { describe, expect, it } from "vitest";

import {
  activityOf,
  activityPath,
  clampToArea,
  expressionFor,
  isNight,
  nextBehaviour,
  NO_STROKE,
  stroke,
  STROKE_WINDOW_MS,
  strollStep,
  type StrokeTracker,
} from "./blobby-engine";

/** A random source that answers these values in turn. */
const rolls = (...values: number[]) => {
  let i = 0;
  return () => values[i++ % values.length]!;
};

describe("nextBehaviour", () => {
  it("is mostly idle, sometimes a stroll, otherwise a doze", () => {
    expect(nextBehaviour(rolls(0.1, 0.5), 12, true).state).toBe("idle");
    expect(nextBehaviour(rolls(0.8, 0.5, 0.2), 12, true)).toMatchObject({
      state: "stroll",
      dir: -1,
    });
    expect(nextBehaviour(rolls(0.8, 0.5, 0.9), 12, true)).toMatchObject({
      state: "stroll",
      dir: 1,
    });
    expect(nextBehaviour(rolls(0.95, 0.5), 12, true).state).toBe("doze");
  });

  it("dozes instead of strolling at night, or when it may not roam", () => {
    expect(nextBehaviour(rolls(0.8, 0.5), 23, true).state).toBe("doze");
    expect(nextBehaviour(rolls(0.8, 0.5), 12, false).state).toBe("doze");
  });

  it("knows when night is", () => {
    expect([isNight(22), isNight(3), isNight(7), isNight(21)]).toEqual([true, true, false, false]);
  });
});

describe("stroke", () => {
  const sweep = (xs: number[], times: number[]): StrokeTracker =>
    xs.reduce((tracker, x, i) => stroke(tracker, x, times[i]!), NO_STROKE);

  it("is pleased by four reversals inside the window", () => {
    expect(sweep([10, 20, 10, 20, 10, 20], [0, 100, 200, 300, 400, 500]).pleased).toBe(true);
  });

  it("is not pleased by a cursor merely passing through, or by slow reversals", () => {
    expect(sweep([10, 20, 30, 40], [0, 100, 200, 300]).pleased).toBe(false);
    const slow = [0, 1, 2, 3, 4, 5].map((i) => i * (STROKE_WINDOW_MS + 1));
    expect(sweep([10, 20, 10, 20, 10, 20], slow).pleased).toBe(false);
  });

  it("ignores a move that goes nowhere", () => {
    expect(stroke({ ...NO_STROKE, x: 5 }, 5, 0)).toMatchObject({ x: 5, dir: 0 });
  });
});

describe("strollStep", () => {
  it("walks, and turns round at either edge instead of leaving the screen", () => {
    expect(strollStep(100, 1, 1000, 0, 500)).toEqual({ x: 128, dir: 1 });
    expect(strollStep(490, 1, 1000, 0, 500)).toEqual({ x: 500, dir: -1 });
    expect(strollStep(10, -1, 1000, 0, 500)).toEqual({ x: 0, dir: 1 });
  });
});

describe("clampToArea", () => {
  it("keeps a window inside the monitor, moving it the least", () => {
    const area = { x: 0, y: 0, width: 1000, height: 800 };
    const size = { width: 200, height: 200 };
    expect(clampToArea({ x: 950, y: -20 }, size, area)).toEqual({ x: 800, y: 0 });
    expect(clampToArea({ x: 100, y: 100 }, size, area)).toEqual({ x: 100, y: 100 });
  });
});

describe("activityOf", () => {
  it("says the most urgent thing first", () => {
    expect(activityOf({ approvals: 2, unread: 5, running: 1 })).toEqual({
      kind: "approvals",
      count: 2,
    });
    expect(activityOf({ approvals: 0, unread: 5, running: 1 })).toEqual({
      kind: "unread",
      count: 5,
    });
    expect(activityOf({ approvals: 0, unread: 0, running: 1 })).toEqual({
      kind: "running",
      count: 1,
    });
    expect(activityOf({ approvals: 0, unread: 0, running: 0 })).toEqual({ kind: "quiet" });
  });

  it("opens the queue for an approval and the runs for a run; the rest open nothing", () => {
    expect(activityPath({ kind: "approvals", count: 1 })).toBe("/runs?tab=approvals");
    expect(activityPath({ kind: "running", count: 1 })).toBe("/runs");
    expect(activityPath({ kind: "unread", count: 1 })).toBeNull();
    expect(activityPath({ kind: "quiet" })).toBeNull();
  });
});

describe("expressionFor", () => {
  it("shows a reaction, then what the agents need, then what it is doing", () => {
    const quiet = { kind: "quiet" } as const;
    expect(expressionFor("happy", { kind: "approvals", count: 1 })).toBe("love");
    expect(expressionFor("wave", quiet)).toBe("happy");
    expect(expressionFor("hop", quiet)).toBe("happy");
    expect(expressionFor("doze", { kind: "approvals", count: 1 })).toBe("surprised");
    expect(expressionFor("idle", { kind: "running", count: 1 })).toBe("thinking");
    expect(expressionFor("doze", quiet)).toBe("sleepy");
    expect(expressionFor("stroll", { kind: "unread", count: 1 })).toBe("idle");
  });
});
