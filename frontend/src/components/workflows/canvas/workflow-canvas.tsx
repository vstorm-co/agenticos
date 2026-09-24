"use client";

import { ReactFlowProvider } from "@xyflow/react";

import type { NodeDefinition, WorkflowDetail } from "@/lib/workflows/types";

import { WorkflowGraphView } from "./workflow-graph-view";

import "@xyflow/react/dist/style.css";

interface WorkflowCanvasProps {
  /** The workflow being edited; its `draft_graph` is seeded into the store by the page. */
  workflow: WorkflowDetail;
  /** The node catalog, for resolving definitions and the connection rules. */
  catalog: NodeDefinition[];
  /** A published version renders read-only. Defaults to the editable draft. */
  readOnly?: boolean;
}

/**
 * The editor canvas — a per-instance `<ReactFlowProvider>` (never a module
 * singleton, so one workflow's editor cannot bleed into another's) wrapping the
 * controlled graph view.
 *
 * The working graph itself lives in the editor store, seeded by the page from
 * `WorkflowDetail.draft_graph`; the canvas only renders it and applies changes
 * back. Read-only mode reuses the same view with dragging, connecting and
 * handles switched off.
 */
export function WorkflowCanvas({ workflow, catalog, readOnly = false }: WorkflowCanvasProps) {
  return (
    <div data-workflow-id={workflow.id}>
      <ReactFlowProvider>
        <WorkflowGraphView catalog={catalog} readOnly={readOnly} />
      </ReactFlowProvider>
    </div>
  );
}
