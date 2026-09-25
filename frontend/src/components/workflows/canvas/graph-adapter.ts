import type { Connection, Edge, Node } from "@xyflow/react";

import { portSchema, portShapesCompatible } from "@/components/workflows/validation";
import type { NodeDefinition, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

/**
 * The pure projection between the store's `WorkflowGraph` and the controlled
 * `@xyflow/react` node/edge props the canvas renders — plus the connection rule
 * the canvas enforces before a drag is drawn.
 *
 * Kept free of React so every branch is unit-testable without a renderer: the
 * canvas component is a thin shell over these functions. Nothing here fetches or
 * mutates; the store owns the graph and every mutation.
 */

/**
 * The output port a node raises its failure through. There is no per-port
 * "is error" flag in #1786's catalog, so the convention is centralized here: an
 * output port with this id is the error port, drawn with a distinct handle and
 * carrying the error-typed edge. One constant so the node handle and the edge
 * variant agree.
 */
export const ERROR_PORT_ID = "error";

/** The catalog key a node instance resolves its definition by — id pinned to version. */
function definitionKey(definitionId: string, version: number): string {
  return `${definitionId}\u0000${version}`;
}

/** Index the catalog by `(id, version)`, the pair a `NodeInstance` pins. */
export function buildCatalogMap(definitions: NodeDefinition[]): Map<string, NodeDefinition> {
  return new Map(definitions.map((def) => [definitionKey(def.id, def.version), def]));
}

/**
 * Each node's resolved definition (or null when the catalog has no matching
 * version), keyed by node id — what both the node projection and the edge
 * variant read.
 */
export function definitionsByNode(
  graph: WorkflowGraph,
  catalog: Map<string, NodeDefinition>,
): Map<string, NodeDefinition | null> {
  return new Map(
    graph.nodes.map((instance) => [
      instance.id,
      catalog.get(definitionKey(instance.definition_id, instance.definition_version)) ?? null,
    ]),
  );
}

/** Whether a port is the distinct, error-carrying output. */
export function isErrorPort(port: { id: string; kind: "input" | "output" }): boolean {
  return port.kind === "output" && port.id === ERROR_PORT_ID;
}

/** The data a rendered node carries: its instance, its resolved definition, the mode. */
export type WorkflowNodeData = {
  instance: NodeInstance;
  definition: NodeDefinition | null;
  readOnly: boolean;
};

export type WorkflowFlowNode = Node<WorkflowNodeData>;

/** The three edge kinds the canvas draws differently. */
export type EdgeVariant = "data" | "error" | "branch";

/** The data a rendered edge carries: its variant and, for a branch, its label. */
export type WorkflowEdgeData = {
  variant: EdgeVariant;
  label: string | null;
};

export type WorkflowFlowEdge = Edge<WorkflowEdgeData>;

/**
 * Project the graph's nodes into `@xyflow/react` nodes. `type` is the node's
 * `kind` bucket, so the matching component in `nodeTypes` renders it; the
 * resolved definition and the read-only flag ride along in `data`.
 */
export function toFlowNodes(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
  readOnly: boolean,
): WorkflowFlowNode[] {
  return graph.nodes.map((instance) => {
    const definition = definitions.get(instance.id) ?? null;
    return {
      id: instance.id,
      type: definition?.kind ?? "action",
      position: instance.layout,
      data: { instance, definition, readOnly },
    };
  });
}

/**
 * The variant and label for one edge: the error variant when it leaves the error
 * port, the branch variant (labeled with the port's name) when it leaves a
 * control node's output, otherwise a plain data edge.
 */
export function edgeVariant(
  sourcePort: string,
  sourceDefinition: NodeDefinition | null,
): WorkflowEdgeData {
  if (sourcePort === ERROR_PORT_ID) return { variant: "error", label: null };
  if (sourceDefinition !== null && sourceDefinition.kind === "control") {
    const port = sourceDefinition.ports.find(
      (candidate) => candidate.id === sourcePort && candidate.kind === "output",
    );
    return { variant: "branch", label: port?.label ?? sourcePort };
  }
  return { variant: "data", label: null };
}

/** The store selection an `@xyflow/react` selection change maps to. */
export function selectionFromFlow(
  selectedNodes: ReadonlyArray<{ id: string }>,
  selectedEdges: ReadonlyArray<{ id: string }>,
): { nodeIds: string[]; edgeIds: string[] } {
  return {
    nodeIds: selectedNodes.map((node) => node.id),
    edgeIds: selectedEdges.map((edge) => edge.id),
  };
}

/** Project the graph's edges into typed `@xyflow/react` edges. */
export function toFlowEdges(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
): WorkflowFlowEdge[] {
  return graph.edges.map((edge) => ({
    id: edge.id,
    type: "workflow",
    source: edge.source_node_id,
    target: edge.target_node_id,
    sourceHandle: edge.source_port,
    targetHandle: edge.target_port,
    data: edgeVariant(edge.source_port, definitions.get(edge.source_node_id) ?? null),
  }));
}

/**
 * Whether a drag may be dropped — the client mirror of rule 3, refusing an
 * incompatible connection before it is drawn. A connection needs both handles,
 * may not loop a node to itself, needs both definitions resolved, and its source
 * output port must be shape-compatible with its target input port (a control
 * port carrying no payload is compatible with anything, per the validation
 * helper).
 */
export function isConnectionValid(
  connection: Connection | Edge,
  definitions: Map<string, NodeDefinition | null>,
): boolean {
  const sourceHandle = connection.sourceHandle ?? null;
  const targetHandle = connection.targetHandle ?? null;
  if (sourceHandle === null || targetHandle === null) return false;
  if (connection.source === connection.target) return false;
  const sourceDefinition = definitions.get(connection.source) ?? null;
  const targetDefinition = definitions.get(connection.target) ?? null;
  if (sourceDefinition === null || targetDefinition === null) return false;
  const sourceSchema = portSchema(sourceDefinition, sourceHandle, "output");
  const targetSchema = portSchema(targetDefinition, targetHandle, "input");
  return portShapesCompatible(sourceSchema, targetSchema);
}
