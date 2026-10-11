import { useCallback, useMemo } from "react";

import type { NodeDefinition, NodePosition, WorkflowEdge } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { buildCatalogMap, definitionsByNode } from "./graph-adapter";
import { type InsertFrom, planInsertion } from "./insertion";

/** Where a step is being added from: after a node's output, or where it was dropped. */
export interface InsertOptions {
  from?: InsertFrom;
  dropAt?: NodePosition;
  between?: WorkflowEdge;
}

/** Add a step the way {@link planInsertion} places and wires it. */
export type InsertNode = (definition: NodeDefinition, options?: InsertOptions) => void;

/**
 * Add a step to the working graph, placed and wired by {@link planInsertion},
 * and open its settings when it has any.
 *
 * Reads the graph, the scope and the selection at the moment of the add rather
 * than subscribing to them, so the palette and every node's "+" can hold one
 * stable callback without re-rendering on each edit.
 */
export function useInsertNode(catalog: NodeDefinition[]): InsertNode {
  const insertNode = useWorkflowEditorStore((state) => state.insertNode);
  const editNode = useWorkflowEditorStore((state) => state.editNode);
  const catalogMap = useMemo(() => buildCatalogMap(catalog), [catalog]);
  return useCallback(
    (definition, options = {}) => {
      const { graph, scopePath, selection } = useWorkflowEditorStore.getState();
      if (graph === null) return;
      const planned = planInsertion({
        graph,
        definitions: definitionsByNode(graph, catalogMap),
        scopePath,
        selectedIds: selection.nodeIds,
        definition,
        ...options,
      });
      insertNode(planned);
      // A step with something to set opens its settings at once: it is added to
      // be configured, and a builder should not have to find it and click it.
      if (definition.config_schema !== null || definition.input_schema !== null) {
        editNode(planned.node.id);
      }
    },
    [insertNode, editNode, catalogMap],
  );
}
