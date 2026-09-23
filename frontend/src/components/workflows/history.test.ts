import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowGraph } from "@/lib/workflows/types";

import {
  DEFAULT_DEBOUNCE_MS,
  DEFAULT_HISTORY_LIMIT,
  History,
  createHistoryRecorder,
  type HistoryFlags,
} from "./history";

/** A minimal graph whose `entry_node_id` doubles as a distinguishable marker. */
function graph(marker: string): WorkflowGraph {
  return { entry_node_id: marker, nodes: [], edges: [], bindings: [], scopes: [] };
}

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

  it("evicts the oldest step past the bound", () => {
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

  it("returns null when redo runs off the top after a reset", () => {
    const h = new History<number>();
    h.reset(1);
    expect(h.redo()).toBeNull();
  });
});

describe("createHistoryRecorder", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("exposes the ported defaults", () => {
    expect(DEFAULT_HISTORY_LIMIT).toBe(100);
    expect(DEFAULT_DEBOUNCE_MS).toBe(250);
  });

  it("starts at the loaded baseline with nothing to undo or redo", () => {
    const r = createHistoryRecorder(graph("base"));
    expect([r.canUndo(), r.canRedo()]).toEqual([false, false]);
    expect(r.undo()).toBeNull();
    expect(r.redo()).toBeNull();
  });

  it("coalesces a burst of changes into one undo step at the default delay", () => {
    const flags: HistoryFlags[] = [];
    const r = createHistoryRecorder(graph("base"), {
      onFlagsChange: (f) => flags.push(f),
    });

    r.record(graph("drag-1"));
    r.record(graph("drag-2"));
    r.record(graph("drag-3"));

    vi.advanceTimersByTime(DEFAULT_DEBOUNCE_MS - 1);
    expect(r.canUndo()).toBe(false);
    expect(flags).toHaveLength(0);

    vi.advanceTimersByTime(1);
    expect(r.canUndo()).toBe(true);
    expect(flags).toEqual([{ canUndo: true, canRedo: false }]);

    // One step back lands on the pre-drag baseline, not on an intermediate frame.
    expect(r.undo()?.entry_node_id).toBe("base");
  });

  it("drops an edit that nets back to the last committed state", () => {
    const r = createHistoryRecorder(graph("base"), { delayMs: 10 });
    r.record(graph("base"));
    vi.advanceTimersByTime(10);
    expect(r.canUndo()).toBe(false);
  });

  it("flushes a pending edit before undo, keeping it redoable", () => {
    const flags: HistoryFlags[] = [];
    const r = createHistoryRecorder(graph("base"), {
      delayMs: 50,
      onFlagsChange: (f) => flags.push(f),
    });

    r.record(graph("edit-a"));
    vi.advanceTimersByTime(50); // edit A committed

    r.record(graph("edit-b")); // still inside the debounce window
    expect(r.undo()?.entry_node_id).toBe("edit-a"); // flushes B, then steps back to A

    // The flushed timer must not fire later and record a stale snapshot.
    vi.advanceTimersByTime(1000);
    expect(r.canRedo()).toBe(true);
    expect(r.redo()?.entry_node_id).toBe("edit-b");
    expect(r.undo()?.entry_node_id).toBe("edit-a");
  });

  it("does not re-record the snapshot an undo restored", () => {
    const r = createHistoryRecorder(graph("base"), { delayMs: 10 });
    r.record(graph("edit"));
    vi.advanceTimersByTime(10);

    const restored = r.undo();
    expect(restored?.entry_node_id).toBe("base");

    // The controller echoes the restored graph back through the change stream.
    r.record(restored as WorkflowGraph);
    vi.advanceTimersByTime(10);
    expect(r.canRedo()).toBe(true); // redo branch survived
    expect(r.redo()?.entry_node_id).toBe("edit");
  });

  it("returns fresh clones the caller cannot use to mutate the stack", () => {
    const r = createHistoryRecorder(graph("base"), { delayMs: 10 });
    r.record(graph("edit"));
    vi.advanceTimersByTime(10);

    const back = r.undo();
    back!.entry_node_id = "tampered";
    // Redo yields the stored snapshot, unaffected by the mutation above.
    expect(r.redo()?.entry_node_id).toBe("edit");
    expect(r.undo()?.entry_node_id).toBe("base");
  });

  it("honours a custom limit, evicting the oldest edits", () => {
    const r = createHistoryRecorder(graph("base"), { limit: 2, delayMs: 5 });
    for (const marker of ["e1", "e2", "e3"]) {
      r.record(graph(marker));
      vi.advanceTimersByTime(5);
    }
    // Only two steps remain: e3 -> e2 -> (bottom), the base and e1 evicted.
    expect(r.undo()?.entry_node_id).toBe("e2");
    expect(r.undo()?.entry_node_id).toBe("e1");
    expect(r.undo()).toBeNull();
  });

  it("reports reachability through redo as well as undo", () => {
    const flags: HistoryFlags[] = [];
    const r = createHistoryRecorder(graph("base"), {
      delayMs: 5,
      onFlagsChange: (f) => flags.push(f),
    });
    r.record(graph("edit"));
    vi.advanceTimersByTime(5);
    r.undo();
    r.redo();
    expect(flags.at(-1)).toEqual({ canUndo: true, canRedo: false });
  });
});
