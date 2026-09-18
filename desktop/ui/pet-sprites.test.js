import { expect, test } from "bun:test";

import { FPS, HEIGHT, KINDS, PETS, WIDTH, compose, frames } from "./pet-sprites.js";

const STATES = Object.keys(FPS);

test("every frame of every pet's every animation is a full grid of palette keys", () => {
  for (const kind of KINDS) {
    for (const state of STATES) {
      for (const dir of [-1, 1]) {
        for (const grid of frames(kind, state, dir)) {
          expect(grid).toHaveLength(HEIGHT);
          for (const row of grid) {
            expect(row).toHaveLength(WIDTH);
            for (const key of row) expect(key === "." || key in PETS[kind].palette).toBe(true);
          }
        }
      }
    }
  }
});

test("every pet's body rows are the grid's width, so a typo in the art fails here", () => {
  for (const kind of KINDS) {
    for (const row of PETS[kind].body) expect(row).toHaveLength(WIDTH);
  }
});

test("a stroll looks the way it is walking", () => {
  for (const kind of KINDS) {
    const [left] = frames(kind, "stroll", -1);
    const [right] = frames(kind, "stroll", 1);
    expect(left).not.toEqual(right);
  }
});

test("a blink closes the eyes without moving anything else", () => {
  for (const kind of KINDS) {
    const [open, , , , blink] = frames(kind, "idle");
    const changed = open.map((row, y) => [...row].filter((key, x) => key !== blink[y][x]).length);
    const total = changed.reduce((a, b) => a + b);
    expect(total).toBeGreaterThan(0);
    expect(total).toBeLessThanOrEqual(8);
  }
});

test("a hop lifts the whole pet and drops nothing off the top", () => {
  for (const kind of KINDS) {
    const [rest, , peak] = frames(kind, "hop");
    const painted = (grid) => grid.reduce((n, row) => n + [...row].filter((key) => key !== ".").length, 0);
    expect(painted(peak)).toBe(painted(rest));
    expect(peak[HEIGHT - 1]).toBe(".".repeat(WIDTH));
  }
});

test("a wave puts an arm where there was none", () => {
  for (const kind of KINDS) {
    const [idle] = frames(kind, "idle");
    const [up] = frames(kind, "wave");
    expect(up).not.toEqual(idle);
  }
});

test("a later layer paints over an earlier one and off-grid cells are dropped", () => {
  const grid = compose([
    { x: 0, y: 0, rows: ["BB"] },
    { x: 1, y: 0, rows: ["D"] },
    { x: WIDTH - 1, y: HEIGHT - 1, rows: ["KK", "KK"] },
  ]);
  expect(grid[0].slice(0, 2)).toBe("BD");
  expect(grid[HEIGHT - 1].at(-1)).toBe("K");
});

test("a pleased pet shows a heart, and a gaze moves only the eyes", () => {
  for (const kind of KINDS) {
    const [first] = frames(kind, "happy");
    expect(first.join("")).toContain("H");
    const [straight] = frames(kind, "idle", 1, 0);
    const [aside] = frames(kind, "idle", 1, 1);
    const changed = straight.reduce((n, row, y) => n + [...row].filter((key, x) => key !== aside[y][x]).length, 0);
    expect(changed).toBeGreaterThan(0);
    expect(changed).toBeLessThanOrEqual(16);
  }
});
