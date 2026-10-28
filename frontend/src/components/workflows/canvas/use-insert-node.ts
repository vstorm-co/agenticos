import { useCallback, useMemo } from "react";

import { suggestedBindingsFor } from "@/components/workflows/apps";
import { nodeOutputBinding } from "@/components/workflows/property-panel/bindings";
import { availableSourceNodes } from "@/components/workflows/validation";
import type {
  Binding,
  NodeDefinition,
  NodePosition,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";
import { type NodeInsertion, useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { buildCatalogMap, definitionsByNode } from "./graph-adapter";
import { type InsertFrom, planInsertion } from "./insertion";

/** Where a step is being added from: after a node's output, or where it was dropped. */
export interface InsertOptions {
  from?: InsertFrom;
  dropAt?: NodePosition;
  between?: WorkflowEdge;
  /** The step's config, when it is added already set up - an app's action, an `mcp.call` for a tool. */
  config?: Record<string, unknown>;
}

/** Add a step the way {@link planInsertion} places and wires it. */
export type InsertNode = (definition: NodeDefinition, options?: InsertOptions) => void;

/**
 * The bindings an app's action starts with: the mail the workflow's trigger delivered,
 * read into the arguments that answer it (`thread_id`, `in_reply_to`, ...). Empty unless
 * the step is a known mail tool and that app's trigger sits upstream of it as planned,
 * so every binding is one the validator accepts.
 */
function suggestedBindings(
  graph: WorkflowGraph,
  plan: NodeInsertion,
  catalog: NodeDefinition[],
): Binding[] {
  // An app's action is an MCP call; a `tool` in any other step's config is not one.
  const tool = plan.node.definition_id === "mcp.call" ? plan.node.config.tool : undefined;
  const suggestion = typeof tool === "string" ? suggestedBindingsFor(tool) : null;
  if (suggestion === null) return [];
  const edges = graph.edges.filter((edge) => edge.id !== plan.split?.edgeId);
  const after: WorkflowGraph = {
    ...graph,
    entry_node_id: plan.becomesEntry ? plan.node.id : graph.entry_node_id,
    nodes: [...graph.nodes, plan.node],
    edges: [
      ...edges,
      ...(plan.split?.tail == null ? [] : [plan.split.tail]),
      ...(plan.edge === null ? [] : [plan.edge]),
    ],
  };
  const upstream = availableSourceNodes(
    after,
    { items: catalog, total: catalog.length },
    plan.node.id,
  );
  const trigger = after.nodes.find(
    (node) => upstream.has(node.id) && suggestion.triggers.includes(node.definition_id),
  );
  if (trigger === undefined) return [];
  return Object.entries(suggestion.fields).map(([argument, field]) =>
    nodeOutputBinding(plan.node.id, `arguments/${argument}`, trigger.id, "out", [field]),
  );
}

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
    (definition, { config, ...options } = {}) => {
      const { graph, scopePath, selection } = useWorkflowEditorStore.getState();
      if (graph === null) return;
      const plan = planInsertion({
        graph,
        definitions: definitionsByNode(graph, catalogMap),
        scopePath,
        selectedIds: selection.nodeIds,
        definition,
        ...options,
      });
      const configured = config === undefined ? plan : { ...plan, node: { ...plan.node, config } };
      // One insertion, so one undo takes the step and its suggested bindings back together.
      const planned = {
        ...configured,
        bindings: [...configured.bindings, ...suggestedBindings(graph, configured, catalog)],
      };
      insertNode(planned);
      // A step with something to set opens its settings at once: it is added to
      // be configured, and a builder should not have to find it and click it.
      if (definition.config_schema !== null || definition.input_schema !== null) {
        editNode(planned.node.id);
      }
    },
    [insertNode, editNode, catalog, catalogMap],
  );
}
