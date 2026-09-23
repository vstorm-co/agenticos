/**
 * Shared builders for the validation tests, and the catalog that mirrors the
 * synthetic node definitions `backend/tests/test_workflow_graph_validation.py` and
 * `..._internals.py` register.
 *
 * The graph shapes the drift test uses are translated straight from those Python
 * fixtures — same nodes, same edges, same bindings — so the TS mirror can be
 * asserted to flag the same rule violations. JSON Schemas here are what the node
 * catalog serves for the Pydantic models the Python tests build (`DebugEchoConfig`,
 * `DebugEchoOutput`, `_RequiredInput`, `_Letter`, `_Number`), so the type-
 * compatibility rule compares the very schemas the backend compares as
 * `model_fields`.
 *
 * Every export here is exercised by the tests — the file is under the 100%
 * coverage gate like the module it supports.
 */

import type {
  Binding,
  JsonSchema,
  NodeCatalog,
  NodeDefinition,
  NodeInstance,
  Port,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

import type { ValidationTranslator } from "./types";

/** A translator that echoes the key and appends any params — enough for the tests. */
export const testTranslator: ValidationTranslator = (key, values) =>
  values === undefined ? key : `${key} ${JSON.stringify(values)}`;

// JSON-Schema fragments, as the catalog serves the Pydantic models.

export const STRING: JsonSchema = { type: "string" };
export const INTEGER: JsonSchema = { type: "integer" };
export const DATETIME: JsonSchema = { type: "string", format: "date-time" };

/** An object schema with a title, properties and a required list — a Pydantic model. */
export function objectSchema(
  title: string,
  properties: Record<string, JsonSchema>,
  required: string[],
): JsonSchema {
  return { type: "object", title, properties, required };
}

export const DEBUG_ECHO_CONFIG = objectSchema("DebugEchoConfig", { message: STRING }, []);
export const DEBUG_ECHO_OUTPUT = objectSchema(
  "DebugEchoOutput",
  { echoed: STRING, received_at: DATETIME },
  ["echoed", "received_at"],
);
export const REQUIRED_INPUT = objectSchema("RequiredInput", { value: STRING }, ["value"]);
/** An all-optional model — Pydantic emits no `required` key for one. */
export const OPTIONAL_INPUT: JsonSchema = {
  type: "object",
  title: "OptionalInput",
  properties: { value: STRING },
};
export const PLAIN_OUTPUT = objectSchema("PlainOutput", { value: STRING }, []);
export const LETTER = objectSchema("Letter", { letter: STRING }, ["letter"]);
export const NUMBER = objectSchema("Number", { letter: INTEGER }, ["letter"]);

export function port(id: string, kind: "input" | "output", schema: JsonSchema | null): Port {
  return { id, label: id, kind, schema };
}

/** Build a definition from a partial over a minimal action-node base. */
export function makeDefinition(
  overrides: Partial<NodeDefinition> & { id: string },
): NodeDefinition {
  return {
    version: 1,
    name: overrides.id,
    category: "test",
    description: "test node",
    kind: "action",
    config_schema: null,
    input_schema: null,
    output_schema: null,
    ports: [],
    effect_kind: "pure",
    retry_guarantee: "idempotent",
    scopes: [],
    ...overrides,
  };
}

/** `debug.echo`, exactly as `backend/app/workflows/nodes/debug_echo` registers it. */
export const DEBUG_ECHO: NodeDefinition = makeDefinition({
  id: "debug.echo",
  name: "Echo",
  category: "debug",
  config_schema: DEBUG_ECHO_CONFIG,
  input_schema: DEBUG_ECHO_CONFIG,
  output_schema: DEBUG_ECHO_OUTPUT,
  ports: [port("in", "input", DEBUG_ECHO_CONFIG), port("out", "output", DEBUG_ECHO_OUTPUT)],
});

export function makeCatalog(items: NodeDefinition[]): NodeCatalog {
  return { items, total: items.length };
}

export function node(
  id: string,
  definitionId: string,
  config: Record<string, unknown> = {},
  version = 1,
): NodeInstance {
  return {
    id,
    definition_id: definitionId,
    definition_version: version,
    config,
    layout: { x: 0, y: 0 },
  };
}

/** A `debug.echo` node instance with the message configured. */
export function echo(id: string): NodeInstance {
  return node(id, "debug.echo", { message: "hi" });
}

export function edge(
  id: string,
  source: string,
  sourcePort: string,
  target: string,
  targetPort: string,
): WorkflowEdge {
  return {
    id,
    source_node_id: source,
    source_port: sourcePort,
    target_node_id: target,
    target_port: targetPort,
  };
}

export function nodeOutputBinding(
  targetNode: string,
  targetField: string,
  sourceNode: string,
  sourcePort: string,
  fieldPath: string[],
): Binding {
  return {
    target_node_id: targetNode,
    target_field: targetField,
    source: { kind: "node_output", node_id: sourceNode, port: sourcePort, field_path: fieldPath },
  };
}

export function literalBinding(targetNode: string, targetField: string, value: unknown): Binding {
  return {
    target_node_id: targetNode,
    target_field: targetField,
    source: { kind: "literal", value },
  };
}

export function graph(parts: {
  entry: string;
  nodes: NodeInstance[];
  edges?: WorkflowEdge[];
  bindings?: Binding[];
}): WorkflowGraph {
  return {
    entry_node_id: parts.entry,
    nodes: parts.nodes,
    edges: parts.edges ?? [],
    bindings: parts.bindings ?? [],
    scopes: [],
  };
}
