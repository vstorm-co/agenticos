import { expect, test } from "bun:test";

import { FPS, HEIGHT, VARIANTS, WIDTH, compose, frames } from "./pet-sprites.js";

const STATES = Object.keys(FPS);

test("every frame of every animation is a full grid of palette keys", () => {
  for (const state of STATES) {
    for (const dir of [-1, 1]) {
      for (const grid of frames(state, dir)) {
        expect(grid).toHaveLength(HEIGHT);
        for (const row of grid) {
          expect(row).toHaveLength(WIDTH);
          for (const key of row) expect(key === "." || key in VARIANTS.orbit).toBe(true);
        }
      }
    }
  }
});

test("every variant colours every key a frame can use", () => {
  const used = new Set(STATES.flatMap((state) => frames(state).flatMap((grid) => [...grid.join("")])));
  used.delete(".");
  for (const palette of Object.values(VARIANTS)) {
    for (const key of used) expect(palette[key]).toMatch(/^#[0-9a-f]{6}$/);
  }
});

test("a stroll looks the way it is walking", () => {
  const [left] = frames("stroll", -1);
  const [right] = frames("stroll", 1);
  expect(left).not.toEqual(right);
});

test("a blink closes the eyes without moving anything else", () => {
  const [open, , , , blink] = frames("idle");
  const changed = open.map((row, y) => [...row].filter((key, x) => key !== blink[y][x]).length);
  expect(changed.reduce((a, b) => a + b)).toBeGreaterThan(0);
  expect(changed.reduce((a, b) => a + b)).toBeLessThanOrEqual(8);
});

test("a hop lifts the whole sprite and drops nothing off the top", () => {
  const [, , peak] = frames("hop");
  expect(peak[0]).toContain("A");
  expect(peak[HEIGHT - 1]).toBe(".".repeat(WIDTH));
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
