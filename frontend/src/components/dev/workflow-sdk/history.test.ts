import { describe, expect, it } from "vitest";

import { History } from "./history";

describe("History", () => {
  it("has nothing to undo or redo until something is recorded", () => {
    const h = new History<number>();
    expect([h.canUndo, h.canRedo, h.undo(), h.redo()]).toEqual([false, false, null, null]);
    h.reset(1);
    expect([h.canUndo, h.canRedo, h.undo(), h.redo()]).toEqual([false, false, null, null]);
  });

  it("walks back and forward through recorded states", () => {
    const h = new History<number>();
    h.reset(1);
    h.record(2);
    h.record(3);
    expect(h.size).toBe(2);
    expect(h.undo()).toBe(2);
    expect(h.undo()).toBe(1);
    expect(h.canUndo).toBe(false);
    expect(h.redo()).toBe(2);
    expect(h.redo()).toBe(3);
    expect(h.canRedo).toBe(false);
  });

  it("drops the redo branch on a new edit", () => {
    const h = new History<number>();
    h.reset(1);
    h.record(2);
    h.undo();
    h.record(9);
    expect(h.canRedo).toBe(false);
    expect(h.undo()).toBe(1);
  });

  it("is bounded", () => {
    const h = new History<number>(3);
    h.reset(0);
    for (const n of [1, 2, 3, 4, 5]) h.record(n);
    expect(h.size).toBe(3);
    expect([h.undo(), h.undo(), h.undo(), h.undo()]).toEqual([4, 3, 2, null]);
  });

  it("treats a reset as a fresh start, not an edit", () => {
    const h = new History<number>();
    h.reset(1);
    h.record(2);
    h.reset(7);
    expect([h.canUndo, h.canRedo, h.size]).toEqual([false, false, 0]);
  });

  it("records into an empty history without a baseline", () => {
    const h = new History<number>();
    h.record(1);
    expect(h.canUndo).toBe(false);
  });
});
