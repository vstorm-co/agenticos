import type { Connection, Edge, Node } from "@xyflow/react";

import { portSchema, portShapesCompatible, UNKNOWN } from "@/components/workflows/validation";
import { ERROR_PORT, effectiveDefinition } from "@/lib/workflows/ports";
import type { Binding, NodeDefinition, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

import { NODE_HEIGHT, NODE_WIDTH } from "./insertion";

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
export const ERROR_PORT_ID = ERROR_PORT;

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
    graph.nodes.map((instance) => {
      const definition = catalog.get(
        definitionKey(instance.definition_id, instance.definition_version),
      );
      return [
        instance.id,
        definition === undefined ? null : effectiveDefinition(instance, definition),
      ];
    }),
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
  /** How many steps a loop's body holds, from the wires as they are now; 0 for any other step. */
  bodySize: number;
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

const NO_IDS: ReadonlySet<string> = new Set();

/**
 * Project the graph's nodes into `@xyflow/react` nodes. `type` is the node's
 * `kind` bucket, so the matching component in `nodeTypes` renders it; the
 * resolved definition and the read-only flag ride along in `data`.
 *
 * `selectedIds` is the store's selection. The nodes are rebuilt from the graph on
 * every edit, and a controlled `<ReactFlow>` takes `selected` from the node it is
 * handed - so a node without the flag reads as deselected, and typing in the
 * property panel (which edits the graph) would close the panel it is typing in.
 */
export function toFlowNodes(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
  readOnly: boolean,
  selectedIds: ReadonlySet<string> = NO_IDS,
): WorkflowFlowNode[] {
  const bodySizes = new Map(
    graph.scopes.map((scope) => [scope.scope_node_id, scope.body_node_ids.length] as const),
  );
  return graph.nodes.map((instance) => {
    const definition = definitions.get(instance.id) ?? null;
    return {
      id: instance.id,
      type: definition?.kind ?? "action",
      position: instance.layout,
      // What the minimap and the first fit go by until the card is measured: a
      // controlled node is handed over without the size xyflow measured for it.
      initialWidth: NODE_WIDTH,
      initialHeight: NODE_HEIGHT,
      selected: selectedIds.has(instance.id),
      data: { instance, definition, readOnly, bodySize: bodySizes.get(instance.id) ?? 0 },
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

/** Project the graph's edges into typed `@xyflow/react` edges, flagging the selected ones. */
export function toFlowEdges(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
  selectedIds: ReadonlySet<string> = NO_IDS,
): WorkflowFlowEdge[] {
  return graph.edges.map((edge) => ({
    id: edge.id,
    type: "workflow",
    source: edge.source_node_id,
    target: edge.target_node_id,
    sourceHandle: edge.source_port,
    targetHandle: edge.target_port,
    selected: selectedIds.has(edge.id),
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

/** The property names of a JSON-Schema object, or none when it declares no properties. */
function propertyNames(schema: unknown): string[] {
  if (typeof schema !== "object" || schema === null) return [];
  const properties = (schema as { properties?: unknown }).properties;
  return typeof properties === "object" && properties !== null ? Object.keys(properties) : [];
}

/** The fields of a JSON-Schema object that hold a list, `list[X]` or `list[X] | None`. */
function listFields(schema: unknown): string[] {
  if (typeof schema !== "object" || schema === null) return [];
  const properties = (schema as { properties?: unknown }).properties;
  if (typeof properties !== "object" || properties === null) return [];
  const holdsList = (field: unknown): boolean => {
    if (typeof field !== "object" || field === null) return false;
    const { type, anyOf } = field as { type?: unknown; anyOf?: unknown };
    return type === "array" || (Array.isArray(anyOf) && anyOf.some(holdsList));
  };
  return Object.entries(properties)
    .filter(([, field]) => holdsList(field))
    .map(([name]) => name);
}

/**
 * The bindings a new edge implies: one per input field, each reading the field of
 * the same name from the source's output.
 *
 * An edge only orders two steps; the values a step reads are its bindings. When
 * an edge joins two data ports of the *same shape* the mapping is unambiguous -
 * every field of the target has exactly one same-named, same-typed counterpart at
 * the source - so drawing the edge can also wire the data, and the reader is not
 * left to bind each field by hand before the graph will publish.
 *
 * Nothing is implied when either end is a control port (it carries no fields), or
 * when the shapes differ and which field feeds which is a choice - except a list:
 * a target taking one list, after a source handing on one, reads that one. A
 * field that is already bound is left alone, and only fields of the target's
 * `input_schema` are bound - the fields a binding may name.
 */
export function autoBindings(
  connection: Connection | Edge,
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
): Binding[] {
  const sourceHandle = connection.sourceHandle ?? null;
  const targetHandle = connection.targetHandle ?? null;
  if (sourceHandle === null || targetHandle === null) return [];
  const sourceDefinition = definitions.get(connection.source) ?? null;
  const targetDefinition = definitions.get(connection.target) ?? null;
  if (sourceDefinition === null || targetDefinition === null) return [];

  const sourceSchema = portSchema(sourceDefinition, sourceHandle, "output");
  const targetSchema = portSchema(targetDefinition, targetHandle, "input");
  if (sourceSchema === UNKNOWN || targetSchema === UNKNOWN) return [];
  if (sourceSchema === null) return [];

  const bound = new Set(
    graph.bindings
      .filter((binding) => binding.target_node_id === connection.target)
      .map((binding) => binding.target_field),
  );
  if (targetSchema === null || !portShapesCompatible(sourceSchema, targetSchema)) {
    // Shapes that differ, or a step that reads its inputs by binding alone, still
    // leave one choice nobody has to make: a step that works on a list, after a
    // step that hands on exactly one - Filter after List records - works on that.
    const lists = listFields(sourceSchema);
    const takes = listFields(targetDefinition.input_schema).filter((field) => !bound.has(field));
    if (lists.length !== 1 || takes.length !== 1) return [];
    return [
      {
        target_node_id: connection.target,
        target_field: takes[0] as string,
        source: {
          kind: "node_output",
          node_id: connection.source,
          port: sourceHandle,
          field_path: [lists[0] as string],
        },
      },
    ];
  }

  const inputFields = new Set(propertyNames(targetDefinition.input_schema));
  return propertyNames(targetSchema)
    .filter((field) => inputFields.has(field) && !bound.has(field))
    .map((field) => ({
      target_node_id: connection.target,
      target_field: field,
      source: {
        kind: "node_output",
        node_id: connection.source,
        port: sourceHandle,
        field_path: [field],
      },
    }));
}
