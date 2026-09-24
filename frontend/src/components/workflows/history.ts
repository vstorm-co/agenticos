import type { WorkflowGraph } from "@/lib/workflows/types";

/**
 * The undo/redo seam — the #1787 history leaf fills this module.
 *
 * The leaf ports #1781's algorithm: a bounded snapshot stack (`History`) plus a
 * debounced recorder that coalesces a drag into one undo step. The stack lives
 * here; the editor store owns no stack of its own and only mirrors reachability,
 * which `createHistoryRecorder` reports through `onFlagsChange`
 * (`useWorkflowEditorStore.setHistoryFlags`). The toolbar reads
 * `history.canUndo`/`canRedo` off the store.
 */
export interface HistoryRecorder {
  /** Push a snapshot (debounced by the leaf so a drag is one step). */
  record: (graph: WorkflowGraph) => void;
  /** Step back, or null at the bottom of the stack. */
  undo: () => WorkflowGraph | null;
  /** Step forward, or null at the top. */
  redo: () => WorkflowGraph | null;
  canUndo: () => boolean;
  canRedo: () => boolean;
  /**
   * Release the recorder: cancel any pending debounce timer and detach
   * `onFlagsChange`. Called by the store before it drops a recorder (a
   * `seedGraph`, `load` or `teardown`), so a timer armed under the old recorder
   * cannot fire its flush after the store has moved on and report flags for a
   * graph that is no longer loaded.
   */
  dispose: () => void;
}

/**
 * How many past snapshots the stack keeps. Older steps beyond this are evicted
 * oldest-first, so undo can walk back at most this many edits. Ported from
 * #1781's lab (100): deep enough that a session never feels it, bounded so a
 * long editing session cannot grow memory without limit. Each entry is one full
 * `WorkflowGraph` snapshot.
 */
export const DEFAULT_HISTORY_LIMIT = 100;

/**
 * How long editing must go quiet before a snapshot is recorded, in
 * milliseconds. A drag emits a change per frame; debouncing collapses the whole
 * gesture into the single snapshot that lands after it settles. Ported from the
 * lab (250ms).
 */
export const DEFAULT_DEBOUNCE_MS = 250;

/** Whether undo and redo can move — reported to the store's `setHistoryFlags`. */
export interface HistoryFlags {
  canUndo: boolean;
  canRedo: boolean;
}

/** Knobs for {@link createHistoryRecorder}; every field has a default. */
export interface HistoryRecorderOptions {
  /** Maximum past snapshots kept. Defaults to {@link DEFAULT_HISTORY_LIMIT}. */
  limit?: number;
  /** Quiet window before a snapshot commits. Defaults to {@link DEFAULT_DEBOUNCE_MS}. */
  delayMs?: number;
  /** Called with fresh reachability whenever the stack moves. */
  onFlagsChange?: (flags: HistoryFlags) => void;
}

/**
 * A bounded undo/redo stack of immutable snapshots.
 *
 * Ported close to unchanged from #1781's lab `History<T>`. `past` holds the
 * steps behind the present, `future` those ahead of it (populated by undo, wiped
 * by any new `record`). The present is not in either list. Bounded by `limit`:
 * once `past` is full a new record evicts the oldest step.
 */
export class History<T> {
  private past: T[] = [];
  private future: T[] = [];
  private present: T | null = null;

  constructor(private readonly limit = DEFAULT_HISTORY_LIMIT) {}

  /** Start over from `snapshot`. Called for the loaded graph, which is not an edit. */
  reset(snapshot: T): void {
    this.past = [];
    this.future = [];
    this.present = snapshot;
  }

  /** Record a new state. Evicts the oldest step past the bound and drops the redo branch. */
  record(snapshot: T): void {
    if (this.present !== null) this.past.push(this.present);
    if (this.past.length > this.limit) this.past.shift();
    this.present = snapshot;
    this.future = [];
  }

  undo(): T | null {
    if (this.present === null) return null;
    const previous = this.past.pop();
    if (previous === undefined) return null;
    this.future.push(this.present);
    this.present = previous;
    return previous;
  }

  redo(): T | null {
    if (this.present === null) return null;
    const next = this.future.pop();
    if (next === undefined) return null;
    this.past.push(this.present);
    this.present = next;
    return next;
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  get canRedo(): boolean {
    return this.future.length > 0;
  }

  /** How many past steps are on the stack — the number undo can walk back. */
  get size(): number {
    return this.past.length;
  }
}

/** A stable string identity for a graph, so an edit that nets to no change is not recorded. */
function graphKey(graph: WorkflowGraph): string {
  return JSON.stringify(graph);
}

/** A deep, detached copy, so a snapshot on the stack cannot alias the caller's working graph. */
function clone(graph: WorkflowGraph): WorkflowGraph {
  return structuredClone(graph);
}

/**
 * A debounced recorder over a bounded {@link History}, coalescing a drag into
 * one undo step.
 *
 * `record(graph)` is called by the canvas on every working-graph change. Rather
 * than push each one, it stores the graph as pending and (re)arms a timer; only
 * when editing has been quiet for `delayMs` does the latest pending graph commit
 * as a single snapshot — so a drag's per-frame changes become one step. A
 * snapshot whose key matches the last committed one is a no-op edit and is
 * dropped. `undo`/`redo` flush any pending edit first (a change still inside the
 * debounce window is not on the stack yet; stepping past it would skip it and
 * make it unrecoverable), then step the stack and mark the restored graph as the
 * last committed one, so re-applying it through the change stream does not record
 * it again. Reachability is reported through `onFlagsChange` after every commit
 * and every step.
 *
 * The baseline is the `initial` graph passed here, established immediately (not
 * debounced) so the first real edit can be undone back to the loaded state. The
 * recorder is created per editor mount — the tree is keyed on `workflowId` and
 * remounted on switch — so there is no cross-workflow reset method and no
 * module-level state.
 *
 * Reachability is reported the instant a real edit arrives, not only when the
 * debounce settles: a pending edit is already undoable (`undo` flushes it
 * first), so `canUndo` counts it and `record` reports immediately. The undo
 * control therefore enables the moment an edit begins rather than 250ms later. A
 * pending edit that nets back to the last committed state is not undoable, so it
 * does not count and does not report.
 */
export function createHistoryRecorder(
  initial: WorkflowGraph,
  options: HistoryRecorderOptions = {},
): HistoryRecorder {
  const { limit = DEFAULT_HISTORY_LIMIT, delayMs = DEFAULT_DEBOUNCE_MS } = options;
  let onFlagsChange = options.onFlagsChange;

  const history = new History<WorkflowGraph>(limit);
  history.reset(clone(initial));
  let lastKey = graphKey(initial);

  let pending: WorkflowGraph | null = null;
  let pendingKey = "";
  let timer: ReturnType<typeof setTimeout> | undefined;

  /** A pending edit that will change the graph — undoable before it even commits. */
  const hasPendingEdit = (): boolean => pending !== null && pendingKey !== lastKey;

  const canUndo = (): boolean => history.canUndo || hasPendingEdit();
  const canRedo = (): boolean => history.canRedo;

  const report = (): void => {
    onFlagsChange?.({ canUndo: canUndo(), canRedo: canRedo() });
  };

  const clearTimer = (): void => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };

  const flush = (): void => {
    clearTimer();
    if (pending === null) return;
    const snapshot = pending;
    const key = pendingKey;
    pending = null;
    pendingKey = "";
    if (key === lastKey) return;
    lastKey = key;
    history.record(snapshot);
    report();
  };

  return {
    record(graph) {
      pending = clone(graph);
      pendingKey = graphKey(graph);
      clearTimer();
      timer = setTimeout(flush, delayMs);
      report();
    },
    undo() {
      flush();
      const snapshot = history.undo();
      if (snapshot === null) return null;
      lastKey = graphKey(snapshot);
      report();
      return clone(snapshot);
    },
    redo() {
      flush();
      const snapshot = history.redo();
      if (snapshot === null) return null;
      lastKey = graphKey(snapshot);
      report();
      return clone(snapshot);
    },
    canUndo,
    canRedo,
    dispose() {
      clearTimer();
      onFlagsChange = undefined;
    },
  };
}
