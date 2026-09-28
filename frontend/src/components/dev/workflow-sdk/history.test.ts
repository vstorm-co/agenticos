import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { History, Recorder } from "./history";

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

describe("Recorder", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function setup() {
    const state = { value: 0 };
    const history = new History<number>();
    const recorder = new Recorder<number>(history, () => ({
      key: String(state.value),
      snapshot: state.value,
    }));
    recorder.baseline();
    return { state, history, recorder };
  }

  it("records one entry once changes have been quiet", () => {
    const { state, history, recorder } = setup();
    state.value = 1;
    recorder.schedule();
    state.value = 2;
    recorder.schedule();
    vi.advanceTimersByTime(249);
    expect(history.size).toBe(0);
    vi.advanceTimersByTime(1);
    expect(history.size).toBe(1);
    expect(history.undo()).toBe(0);
  });

  it("does not record a change that leaves the state as it was", () => {
    const { history, recorder } = setup();
    recorder.schedule();
    vi.advanceTimersByTime(250);
    expect(history.size).toBe(0);
  });

  it("undo flushes a pending edit first, so it stays undoable and redoable", () => {
    const { state, history, recorder } = setup();
    state.value = 1;
    recorder.schedule();
    vi.advanceTimersByTime(250);
    state.value = 2; // edit B, still inside the debounce window
    recorder.schedule();
    vi.advanceTimersByTime(100);

    // One step back lands on A, not on the baseline.
    expect(recorder.undo()).toBe(1);
    state.value = 1; // what the controller does: put the restored state in the store
    recorder.restored("1");
    vi.advanceTimersByTime(1000);
    // The timer the flush cleared does not fire later and record a stale state.
    expect(history.size).toBe(1);
    expect(recorder.redo()).toBe(2);
  });

  it("redo flushes a pending edit first", () => {
    const { state, history, recorder } = setup();
    state.value = 1;
    recorder.schedule();
    vi.advanceTimersByTime(250);
    expect(recorder.undo()).toBe(0);
    state.value = 0;
    recorder.restored("0");
    state.value = 5; // a new edit after the undo, still pending
    recorder.schedule();
    // The pending edit is recorded (dropping the redo branch) before redo steps.
    expect(recorder.redo()).toBeNull();
    expect(history.size).toBe(1);
    expect(history.canRedo).toBe(false);
  });

  it("does not record the state an undo restored", () => {
    const { state, history, recorder } = setup();
    state.value = 1;
    recorder.schedule();
    vi.advanceTimersByTime(250);
    state.value = history.undo() ?? -1;
    recorder.restored("0");
    recorder.flush();
    expect(history.size).toBe(0);
    expect(history.canRedo).toBe(true);
  });

  it("cancels a pending record", () => {
    const { state, history, recorder } = setup();
    state.value = 1;
    recorder.schedule();
    recorder.cancel();
    vi.advanceTimersByTime(1000);
    expect(history.size).toBe(0);
  });
});
