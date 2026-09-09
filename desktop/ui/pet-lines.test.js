import { expect, test } from "bun:test";

import { LINES, pickLine } from "./pet-lines.js";
import { KINDS } from "./pet-sprites.js";

test("every pet has lines, and none is wider than its bubble can carry", () => {
  for (const kind of KINDS) {
    expect(LINES[kind].length).toBeGreaterThan(1);
    for (const line of LINES[kind]) expect(line.length).toBeLessThanOrEqual(26);
  }
});

test("a pet does not repeat the line it just said", () => {
  const last = LINES.amigo[0];
  for (let i = 0; i < 20; i += 1) expect(pickLine("amigo", () => i / 20, last)).not.toBe(last);
});
