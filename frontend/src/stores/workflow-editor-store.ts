"use client";

import {
  applyEdgeChanges as rfApplyEdgeChanges,
  applyNodeChanges as rfApplyNodeChanges,
  type Connection,
  type EdgeChange,
  type Node as FlowNode,
  type NodeChange,
} from "@xyflow/react";
import { create } from "zustand";

import { createHistoryRecorder, type HistoryRecorder } from "@/components/workflows/history";
import type {
  Binding,
  NodeDefinition,
  NodeInstance,
  NodePosition,
  ScopeBoundary,
  Uuid,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

/**
 * The workflow editor's ephemeral state — everything that is *not* server data,
 * plus the single source of truth for the in-progress draft graph.
 *
 * The design keeps *server* data (the persisted `WorkflowDetail`) in the
 * TanStack Query cache; the **working copy** being edited lives here, as `graph`.
 * The canvas leaf renders `graph` as controlled `@xyflow/react` props and applies
 * every change back through this store, so palette, property panel, history and
 * clipboard all read and mutate one graph rather than a per-leaf copy.
 *
 * ## Seams for the leaf branches
 *
 * The slices and their setters are defined here so a leaf fills *behaviour*
 * without redefining the store's public shape:
 *
 * - **Working graph** (`#1787` canvas leaf) is seeded by the editor page from
 *   `WorkflowDetail.draft_graph` (`seedGraph`) and mutated through `addNode`,
 *   `connectNodes`, `applyNodeChanges`/`applyEdgeChanges`, `deleteSelection`,
 *   `updateNodeConfig`, `upsertBinding`/`removeBinding` and `insertSubgraph`.
 *   Every mutation marks the draft dirty and records a history snapshot.
 * - **Canvas selection** (`#1787` canvas leaf) drives `setSelection` /
 *   `clearSelection` from `<ReactFlow>`'s `onSelectionChange`.
 * - **Undo/redo** (history leaf, `components/workflows/history.ts`) keeps the
 *   bounded snapshot stack in its own module; the store owns the recorder for
 *   the current graph and exposes `undo`/`redo`, reporting reachability here via
 *   `setHistoryFlags`; the toolbar reads `history.canUndo`/`canRedo`.
 * - **Clipboard** (clipboard leaf, `components/workflows/clipboard.ts`) computes
 *   a remapped selection and stores it via `setClipboard`; the canvas pastes it
 *   back through `insertSubgraph`.
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
 * working graph; the shape is the flat `WorkflowGraph` sub-lists — the copied
 * nodes, the edges induced among them, the bindings those nodes target, and any
 * fully contained scope. It is a self-contained snapshot: paste re-ids it
 * against the current graph, so the originals may be deleted or the workflow
 * switched without the clip going stale. `body_node_ids` is re-mapped on paste,
 * never server-authored here.
 */
export interface WorkflowClipboard {
  nodes: NodeInstance[];
  edges: WorkflowEdge[];
  bindings: Binding[];
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
  /** The working draft graph, or null before the page seeds it / after teardown. */
  graph: WorkflowGraph | null;
  /** The foreach scope, root-to-current (empty at the root scope). */
  scopePath: Uuid[];
  selection: EditorSelection;
  clipboard: WorkflowClipboard | null;
  history: HistoryFlags;
  conflict: ConflictState | null;

  load: (input: LoadEditorInput) => void;
  teardown: () => void;

  /** Seed the working graph from the loaded draft and start a fresh history stack. */
  seedGraph: (graph: WorkflowGraph) => void;

  /** Apply a batch of `@xyflow/react` node changes (drag, remove) to the graph. */
  applyNodeChanges: (changes: NodeChange[]) => void;
  /** Apply a batch of `@xyflow/react` edge changes (remove) to the graph. */
  applyEdgeChanges: (changes: EdgeChange[]) => void;
  /** Insert a node for `definition` at `position`, returning its new id. */
  addNode: (definition: NodeDefinition, position: NodePosition) => Uuid;
  /** Add an edge for a validated `@xyflow/react` connection. */
  connectNodes: (connection: Connection) => void;
  /** Delete the selected nodes and edges, pruning anything left dangling. */
  deleteSelection: () => void;
  /** Replace one node's static `config`. */
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
  /** Set (or replace) the binding on one node field. */
  upsertBinding: (binding: Binding) => void;
  /** Remove the binding on one node field, if any. */
  removeBinding: (targetNodeId: Uuid, targetField: string) => void;
  /** Merge an already re-ided clip into the graph and select what it added. */
  insertSubgraph: (sub: WorkflowClipboard) => void;

  /** Step the graph back one history entry, if any. */
  undo: () => void;
  /** Step the graph forward one history entry, if any. */
  redo: () => void;

  /** The working graph, for a caller outside React (the clipboard handler). */
  getGraph: () => WorkflowGraph | null;
  /** The single selected node, or null when zero or many are selected. */
  getSelectedNode: () => NodeInstance | null;

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

/** The blank graph a mutation falls back to before the page has seeded one. */
const EMPTY_GRAPH: WorkflowGraph = {
  entry_node_id: "",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

/** The ephemeral slices reset on every `load` and cleared on `teardown`. */
const CLEARED = {
  isDirty: false,
  graph: null as WorkflowGraph | null,
  scopePath: [] as Uuid[],
  selection: EMPTY_SELECTION,
  clipboard: null,
  history: NO_HISTORY,
  conflict: null,
} as const;

/**
 * Drop everything the current node set no longer supports — an edge or binding
 * or scope that names a removed node — and re-home the entry on the first
 * surviving node if it was the one removed. The client mirror of the invariant
 * the server keeps: the graph never references a node it does not hold.
 */
function pruneToNodes(graph: WorkflowGraph): WorkflowGraph {
  const ids = new Set(graph.nodes.map((node) => node.id));
  const edges = graph.edges.filter(
    (edge) => ids.has(edge.source_node_id) && ids.has(edge.target_node_id),
  );
  const bindings = graph.bindings.filter(
    (binding) =>
      ids.has(binding.target_node_id) &&
      (binding.source.kind !== "node_output" || ids.has(binding.source.node_id)),
  );
  const scopes = graph.scopes.filter(
    (scope) =>
      ids.has(scope.scope_node_id) &&
      ids.has(scope.exit_node_id) &&
      scope.body_node_ids.every((id) => ids.has(id)),
  );
  const firstNode = graph.nodes[0];
  const entry_node_id = ids.has(graph.entry_node_id) ? graph.entry_node_id : (firstNode?.id ?? "");
  return { entry_node_id, nodes: graph.nodes, edges, bindings, scopes };
}

/** A stable signature over node identity and layout, to tell a real edit from a re-select. */
function nodesSignature(nodes: NodeInstance[]): string {
  return nodes.map((node) => `${node.id}:${node.layout.x}:${node.layout.y}`).join("|");
}

export const useWorkflowEditorStore = create<WorkflowEditorState>()((set, get) => {
  /**
   * The undo/redo stack for the *current* graph, or null before it is seeded.
   * Held here rather than in the reactive state because it is an imperative
   * object, not a value the UI renders; it is recreated per `seedGraph` and
   * cleared on `load`/`teardown`, so no stack survives a workflow switch.
   */
  let recorder: HistoryRecorder | null = null;

  /** Set the graph, mark the draft dirty and record a history snapshot. */
  const commit = (graph: WorkflowGraph): void => {
    set({ graph, isDirty: true });
    recorder?.record(graph);
  };

  return {
    workflowId: null,
    generation: 0,
    expectedRevision: null,
    ...CLEARED,

    load: ({ workflowId, expectedRevision }) => {
      recorder = null;
      set((state) => ({
        ...CLEARED,
        workflowId,
        expectedRevision,
        generation: state.generation + 1,
      }));
    },

    teardown: () => {
      recorder = null;
      set((state) => ({
        ...CLEARED,
        workflowId: null,
        expectedRevision: null,
        generation: state.generation + 1,
      }));
    },

    seedGraph: (graph) => {
      recorder = createHistoryRecorder(graph, {
        onFlagsChange: (flags) => get().setHistoryFlags(flags),
      });
      set({ graph, history: NO_HISTORY });
    },

    applyNodeChanges: (changes) => {
      const { graph } = get();
      if (graph === null) return;
      const flowNodes: FlowNode[] = graph.nodes.map((node) => ({
        id: node.id,
        position: node.layout,
        data: {},
      }));
      const applied = rfApplyNodeChanges(changes, flowNodes);
      const byId = new Map(graph.nodes.map((node) => [node.id, node] as const));
      const nodes: NodeInstance[] = [];
      for (const flow of applied) {
        const instance = byId.get(flow.id);
        if (instance === undefined) continue;
        nodes.push({ ...instance, layout: { x: flow.position.x, y: flow.position.y } });
      }
      if (nodesSignature(nodes) === nodesSignature(graph.nodes)) return;
      commit(pruneToNodes({ ...graph, nodes }));
    },

    applyEdgeChanges: (changes) => {
      const { graph } = get();
      if (graph === null) return;
      const flowEdges = graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.source_node_id,
        target: edge.target_node_id,
      }));
      const applied = rfApplyEdgeChanges(changes, flowEdges);
      // Only a removal changes the edge count; a selection change leaves it, and
      // this editor offers no edge reconnection, so nothing else can differ.
      if (applied.length === graph.edges.length) return;
      const kept = new Set(applied.map((edge) => edge.id));
      commit({ ...graph, edges: graph.edges.filter((edge) => kept.has(edge.id)) });
    },

    addNode: (definition, position) => {
      const base = get().graph ?? EMPTY_GRAPH;
      const id = crypto.randomUUID();
      const node: NodeInstance = {
        id,
        definition_id: definition.id,
        definition_version: definition.version,
        config: {},
        layout: position,
      };
      const entry_node_id = base.nodes.length === 0 ? id : base.entry_node_id;
      commit({ ...base, entry_node_id, nodes: [...base.nodes, node] });
      return id;
    },

    connectNodes: (connection) => {
      const { graph } = get();
      if (graph === null) return;
      const { source, target, sourceHandle, targetHandle } = connection;
      if (sourceHandle === null || targetHandle === null) return;
      const edge: WorkflowEdge = {
        id: crypto.randomUUID(),
        source_node_id: source,
        source_port: sourceHandle,
        target_node_id: target,
        target_port: targetHandle,
      };
      commit({ ...graph, edges: [...graph.edges, edge] });
    },

    deleteSelection: () => {
      const { graph, selection } = get();
      if (graph === null) return;
      const nodeIds = new Set(selection.nodeIds);
      const edgeIds = new Set(selection.edgeIds);
      if (nodeIds.size === 0 && edgeIds.size === 0) return;
      const nodes = graph.nodes.filter((node) => !nodeIds.has(node.id));
      const edges = graph.edges.filter((edge) => !edgeIds.has(edge.id));
      commit(pruneToNodes({ ...graph, nodes, edges }));
      set({ selection: EMPTY_SELECTION });
    },

    updateNodeConfig: (nodeId, config) => {
      const { graph } = get();
      if (graph === null) return;
      const nodes = graph.nodes.map((node) => (node.id === nodeId ? { ...node, config } : node));
      commit({ ...graph, nodes });
    },

    upsertBinding: (binding) => {
      const { graph } = get();
      if (graph === null) return;
      const others = graph.bindings.filter(
        (existing) =>
          !(
            existing.target_node_id === binding.target_node_id &&
            existing.target_field === binding.target_field
          ),
      );
      commit({ ...graph, bindings: [...others, binding] });
    },

    removeBinding: (targetNodeId, targetField) => {
      const { graph } = get();
      if (graph === null) return;
      const bindings = graph.bindings.filter(
        (binding) =>
          !(binding.target_node_id === targetNodeId && binding.target_field === targetField),
      );
      commit({ ...graph, bindings });
    },

    insertSubgraph: (sub) => {
      const { graph } = get();
      if (graph === null) return;
      const first = sub.nodes[0];
      const entry_node_id =
        graph.nodes.length === 0 && first !== undefined ? first.id : graph.entry_node_id;
      commit({
        entry_node_id,
        nodes: [...graph.nodes, ...sub.nodes],
        edges: [...graph.edges, ...sub.edges],
        bindings: [...graph.bindings, ...sub.bindings],
        scopes: [...graph.scopes, ...sub.scopes],
      });
      set({ selection: { nodeIds: sub.nodes.map((node) => node.id), edgeIds: [] } });
    },

    undo: () => {
      if (recorder === null) return;
      const snapshot = recorder.undo();
      if (snapshot === null) return;
      set({ graph: snapshot, isDirty: true });
    },

    redo: () => {
      if (recorder === null) return;
      const snapshot = recorder.redo();
      if (snapshot === null) return;
      set({ graph: snapshot, isDirty: true });
    },

    getGraph: () => get().graph,

    getSelectedNode: () => {
      const { graph, selection } = get();
      if (graph === null || selection.nodeIds.length !== 1) return null;
      const [id] = selection.nodeIds;
      return graph.nodes.find((node) => node.id === id) ?? null;
    },

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
  };
});
