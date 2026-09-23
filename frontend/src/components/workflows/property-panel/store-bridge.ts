"use client";

import { useWorkflowEditorStore, type WorkflowEditorState } from "@/stores/workflow-editor-store";
import type { Binding, NodeInstance, Uuid, WorkflowGraph } from "@/lib/workflows/types";

/**
 * The graph-editing surface the canvas leaf adds to the editor store in parallel
 * (#1787). It is declared here, not in the store — this leaf owns only
 * `property-panel/**` and must not touch the store definition — so the panel
 * type-checks against the agreed API before the two branches integrate. Once they
 * merge, `WorkflowEditorState` carries these itself and the cast in
 * {@link usePanelStore} is a harmless widening.
 *
 * The panel never writes a runtime value into `config`: an `input_schema` leaf and
 * an `x-bindable` leaf go through `upsertBinding` / `removeBinding`; only a static
 * `config_schema` leaf (a resource pin, a literal setting) goes through
 * `updateNodeConfig`.
 */
export interface WorkflowGraphActions {
  /** The single selected node, or null for an empty or multi-selection. */
  getSelectedNode: () => NodeInstance | null;
  /** The graph currently being edited, or null before one loads. */
  getGraph: () => WorkflowGraph | null;
  /** Replace one node's static `config` wholesale. */
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
  /** Add or replace a binding, keyed by `(target_node_id, target_field)`. */
  upsertBinding: (binding: Binding) => void;
  /** Remove the binding on one field, if any. */
  removeBinding: (targetNodeId: Uuid, targetField: string) => void;
}

/** The editor store as the panel sees it — the ephemeral slices plus the graph seam. */
export type PanelStore = WorkflowEditorState & WorkflowGraphActions;

/**
 * Subscribe the panel to the whole editor store, so a graph edit made anywhere —
 * the canvas, or the panel's own `upsertBinding` — re-renders it. The seam methods
 * are read through {@link WorkflowGraphActions}; the cast is the one place the
 * panel bridges to that surface (see {@link WorkflowGraphActions}).
 */
export function usePanelStore(): PanelStore {
  return useWorkflowEditorStore() as PanelStore;
}
