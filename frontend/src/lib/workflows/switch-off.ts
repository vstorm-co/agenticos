import { TRIGGER_IDS } from "./triggers";
import type { NodeDefinition, NodeInstance, WorkflowGraph } from "./types";

/** A loop's own item and result steps: every iteration starts them, wired or not. */
export function isLoopPart(definitionId: string): boolean {
  return definitionId === "loop.item" || definitionId === "loop.yield";
}

/** Whether any connection starts or ends at `nodeId`. */
export function isWired(graph: WorkflowGraph, nodeId: string): boolean {
  return graph.edges.some((e) => e.source_node_id === nodeId || e.target_node_id === nodeId);
}

/**
 * Whether the editor offers to switch `node` off or back on. A step that is off can
 * always be switched back on. Otherwise the trigger and a loop's item and result
 * steps stay on; a step that decides the way may be switched off only while it has
 * no connection, since connected it would leave the run with no way to go. Mirrors
 * what rule 13 refuses at publish.
 */
export function canSwitchOff(
  graph: WorkflowGraph,
  node: NodeInstance,
  definition: NodeDefinition | null | undefined,
): boolean {
  if (node.disabled === true) return true;
  if (
    node.id === graph.entry_node_id ||
    TRIGGER_IDS.has(node.definition_id) ||
    isLoopPart(node.definition_id)
  )
    return false;
  return definition?.kind !== "control" || !isWired(graph, node.id);
}
