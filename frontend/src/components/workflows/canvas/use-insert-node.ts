import { useCallback, useMemo } from "react";

import type { NodeDefinition, NodePosition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { buildCatalogMap, definitionsByNode } from "./graph-adapter";
import { type InsertFrom, planInsertion } from "./insertion";

/** Where a step is being added from: after a node's output, or where it was dropped. */
export interface InsertOptions {
  from?: InsertFrom;
  dropAt?: NodePosition;
}

/** Add a step the way {@link planInsertion} places and wires it. */
export type InsertNode = (definition: NodeDefinition, options?: InsertOptions) => void;

/**
 * Add a step to the working graph, placed and wired by {@link planInsertion}.
 *
 * Reads the graph, the scope and the selection at the moment of the add rather
 * than subscribing to them, so the palette and every node's "+" can hold one
 * stable callback without re-rendering on each edit.
 */
export function useInsertNode(catalog: NodeDefinition[]): InsertNode {
  const insertNode = useWorkflowEditorStore((state) => state.insertNode);
  const catalogMap = useMemo(() => buildCatalogMap(catalog), [catalog]);
  return useCallback(
    (definition, options = {}) => {
      const { graph, scopePath, selection } = useWorkflowEditorStore.getState();
      if (graph === null) return;
      insertNode(
        planInsertion({
          graph,
          definitions: definitionsByNode(graph, catalogMap),
          scopePath,
          selectedIds: selection.nodeIds,
          definition,
          ...options,
        }),
      );
    },
    [insertNode, catalogMap],
  );
}
