"use client";

import { create } from "zustand";

import type { NodeInstance, ScopeBoundary, Uuid, WorkflowEdge } from "@/lib/workflows/types";

/**
 * The workflow editor's ephemeral state — everything that is *not* server data.
 *
 * The graph itself lives in the TanStack Query cache (`useWorkflow`) and, while
 * being edited, in the canvas leaf's own `@xyflow/react` state; it never lives
 * here. This store owns only what the design lists as ephemeral: selection,
 * clipboard, the undo/redo flags, the foreach scope path, the dirty flag, the
 * autosave conflict banner, and the generation counter that guards a save.
 *
 * ## Seams for the leaf branches
 *
 * The slices and their setters are defined here so a leaf fills *behaviour*
 * without redefining the store's public shape:
 *
 * - **Canvas selection** (`#1787` canvas leaf) drives `setSelection` /
 *   `clearSelection` from `<ReactFlow>`'s `onSelectionChange`.
 * - **Undo/redo** (history leaf, `components/workflows/history.ts`) keeps the
 *   bounded snapshot stack in its own module and reports reachability here via
 *   `setHistoryFlags`; the toolbar reads `history.canUndo`/`canRedo`.
 * - **Clipboard** (clipboard leaf, `components/workflows/clipboard.ts`) computes
 *   a remapped selection and stores it via `setClipboard`; paste reads it back.
 * - **Foreach scope** (foreach leaf) pushes/pops `scopePath` with `enterScope` /
 *   `exitScope`; the breadcrumb, palette filter and binding-picker reachability
 *   all read `scopePath`.
 * - **Autosave + conflict** (autosave leaf, ports `save-handler.ts`) reads
 *   `beginSave()` before dispatching a draft `PATCH`, checks `isSaveCurrent`
 *   when it resolves, calls `markSaved` on success and `setConflict` on a 409.
 *
 * ## Generation guard and remount
 *
 * The editor tree is keyed on `workflowId` and remounted on switch, and `load`
 * bumps `generation` every time. A save captured under one generation is
 * refused by `isSaveCurrent` once another `load` (a remount, or a switch to a
 * different workflow) has bumped it — the guard that stops a slow save from a
 * previous editor instance landing on the current one.
 */

/** What the canvas has selected. Node and edge selections are tracked apart. */
export interface EditorSelection {
  nodeIds: Uuid[];
  edgeIds: Uuid[];
}

/**
 * A copied selection, ready to paste. The clipboard leaf produces this from the
 * working graph; the shape is the flat `WorkflowGraph` sub-lists, minus the
 * server-derived `body_node_ids` remapping the leaf handles on paste.
 */
export interface WorkflowClipboard {
  nodes: NodeInstance[];
  edges: WorkflowEdge[];
  scopes: ScopeBoundary[];
}

/** Whether undo and redo can move — the history leaf reports this; the toolbar reads it. */
export interface HistoryFlags {
  canUndo: boolean;
  canRedo: boolean;
}

/**
 * The draft-conflict banner state. Set from a `409` on autosave or publish,
 * carrying the revision the server says is current so **Overwrite** can resend
 * against it.
 */
export interface ConflictState {
  currentRevision: number;
}

/**
 * A token the autosave leaf captures before it builds a draft request, and
 * checks against the store when the request resolves.
 */
export interface SaveToken {
  generation: number;
  workflowId: Uuid | null;
}

/** Everything the editor page hands the store when a workflow loads. */
export interface LoadEditorInput {
  workflowId: Uuid;
  /** The `draft_revision` the detail read carried — the first `expected_revision`. */
  expectedRevision: number;
}

export interface WorkflowEditorState {
  /** The workflow being edited, or null before the first `load` / after `teardown`. */
  workflowId: Uuid | null;
  /** Bumped on every `load` and `teardown`; the guard's monotonic clock. */
  generation: number;
  /** The revision the next draft save must send as `expected_revision`. */
  expectedRevision: number | null;
  /** Whether the working graph has un-saved edits. */
  isDirty: boolean;
  /** The foreach scope, root-to-current (empty at the root scope). */
  scopePath: Uuid[];
  selection: EditorSelection;
  clipboard: WorkflowClipboard | null;
  history: HistoryFlags;
  conflict: ConflictState | null;

  load: (input: LoadEditorInput) => void;
  teardown: () => void;

  setSelection: (selection: EditorSelection) => void;
  clearSelection: () => void;

  setScopePath: (scopePath: Uuid[]) => void;
  enterScope: (scopeNodeId: Uuid) => void;
  exitScope: () => void;

  setClipboard: (clipboard: WorkflowClipboard | null) => void;
  setHistoryFlags: (history: HistoryFlags) => void;

  markDirty: () => void;
  markSaved: (revision: number) => void;
  setExpectedRevision: (revision: number) => void;

  setConflict: (currentRevision: number) => void;
  clearConflict: () => void;

  /** Snapshot the guard token before dispatching a save. */
  beginSave: () => SaveToken;
  /** Whether a captured token still names the current editor instance. */
  isSaveCurrent: (token: SaveToken) => boolean;
}

const EMPTY_SELECTION: EditorSelection = { nodeIds: [], edgeIds: [] };
const NO_HISTORY: HistoryFlags = { canUndo: false, canRedo: false };

/** The ephemeral slices reset on every `load` and cleared on `teardown`. */
const CLEARED = {
  isDirty: false,
  scopePath: [] as Uuid[],
  selection: EMPTY_SELECTION,
  clipboard: null,
  history: NO_HISTORY,
  conflict: null,
} as const;

export const useWorkflowEditorStore = create<WorkflowEditorState>()((set, get) => ({
  workflowId: null,
  generation: 0,
  expectedRevision: null,
  ...CLEARED,

  load: ({ workflowId, expectedRevision }) =>
    set((state) => ({
      ...CLEARED,
      workflowId,
      expectedRevision,
      generation: state.generation + 1,
    })),

  teardown: () =>
    set((state) => ({
      ...CLEARED,
      workflowId: null,
      expectedRevision: null,
      generation: state.generation + 1,
    })),

  setSelection: (selection) => set({ selection }),
  clearSelection: () => set({ selection: EMPTY_SELECTION }),

  setScopePath: (scopePath) => set({ scopePath }),
  enterScope: (scopeNodeId) => set((state) => ({ scopePath: [...state.scopePath, scopeNodeId] })),
  exitScope: () => set((state) => ({ scopePath: state.scopePath.slice(0, -1) })),

  setClipboard: (clipboard) => set({ clipboard }),
  setHistoryFlags: (history) => set({ history }),

  markDirty: () => set({ isDirty: true }),
  markSaved: (revision) => set({ isDirty: false, expectedRevision: revision, conflict: null }),
  setExpectedRevision: (revision) => set({ expectedRevision: revision }),

  setConflict: (currentRevision) => set({ conflict: { currentRevision } }),
  clearConflict: () => set({ conflict: null }),

  beginSave: () => {
    const { generation, workflowId } = get();
    return { generation, workflowId };
  },
  isSaveCurrent: (token) => {
    const { generation, workflowId } = get();
    return token.generation === generation && token.workflowId === workflowId;
  },
}));
