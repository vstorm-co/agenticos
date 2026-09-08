import { expect, test } from "bun:test";

import { STROLL_SPEED, clampToArea, frameIndex, logicalArea, nextBehaviour, strollStep } from "./pet-engine.js";

function rolls(...values) {
  const queue = [...values];
  return () => queue.shift() ?? 0;
}

test("frames advance at the animation's rate and wrap", () => {
  expect(frameIndex("idle", 0, 6)).toBe(0);
  expect(frameIndex("idle", 999, 6)).toBe(2);
  expect(frameIndex("idle", 2000, 6)).toBe(0);
});

test("the ambient roll picks idle most of the time and a doze rarely", () => {
  expect(nextBehaviour(rolls(0.1, 0.5)).state).toBe("idle");
  expect(nextBehaviour(rolls(0.6, 0.5)).state).toBe("look");
  expect(nextBehaviour(rolls(0.8, 0.5, 0.2))).toMatchObject({ state: "stroll", dir: -1 });
  expect(nextBehaviour(rolls(0.8, 0.5, 0.9))).toMatchObject({ state: "stroll", dir: 1 });
  expect(nextBehaviour(rolls(0.95, 0.5)).state).toBe("doze");
});

test("a behaviour lasts a bounded, non-zero time", () => {
  for (const roll of [0, 0.6, 0.8, 0.95]) {
    const { ms } = nextBehaviour(rolls(roll, 0, 0));
    expect(ms).toBeGreaterThan(1000);
    expect(ms).toBeLessThan(20000);
  }
});

test("a stroll moves at its speed and turns round at the edges", () => {
  expect(strollStep(100, 1, 1000, 0, 500)).toEqual({ x: 100 + STROLL_SPEED, dir: 1 });
  expect(strollStep(495, 1, 1000, 0, 500)).toEqual({ x: 500, dir: -1 });
  expect(strollStep(5, -1, 1000, 0, 500)).toEqual({ x: 0, dir: 1 });
});

test("a monitor's work area is preferred and scaled to logical pixels", () => {
  const monitor = {
    scaleFactor: 2,
    position: { x: 0, y: 0 },
    size: { width: 2880, height: 1800 },
    workArea: { position: { x: 0, y: 50 }, size: { width: 2880, height: 1750 } },
  };
  expect(logicalArea(monitor)).toEqual({ x: 0, y: 25, width: 1440, height: 875 });
  delete monitor.workArea;
  expect(logicalArea(monitor)).toEqual({ x: 0, y: 0, width: 1440, height: 900 });
});

test("a pet outside the screen is brought back to its edge", () => {
  const area = { x: 0, y: 0, width: 1440, height: 900 };
  const size = { width: 112, height: 152 };
  expect(clampToArea({ x: -30, y: 2000 }, size, area)).toEqual({ x: 0, y: 748 });
  expect(clampToArea({ x: 300, y: 300 }, size, area)).toEqual({ x: 300, y: 300 });
});
