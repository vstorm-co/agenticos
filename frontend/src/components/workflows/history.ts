import type { WorkflowGraph } from "@/lib/workflows/types";

/**
 * The undo/redo seam — the #1787 history leaf fills this module.
 *
 * The leaf ports #1781's algorithm: a bounded snapshot stack plus a debounced
 * `Recorder` that coalesces a drag into one undo step. It keeps the stack in
 * here and reports reachability to the editor store via `setHistoryFlags`; the
 * store owns no stack of its own.
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
}

// TODO(#1787 history leaf): implement `createHistoryRecorder()` returning a
// bounded stack over `HistoryRecorder`, wired to the store's `setHistoryFlags`.
