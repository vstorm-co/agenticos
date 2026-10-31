/** Runnable local examples. Resource-backed templates are provisioned by the server. */

import type { Binding, Uuid, WorkflowGraph } from "@/lib/workflows/types";

/** A debug node instance at a fixed canvas position; both are version 1. */
function debugNode(id: Uuid, definitionId: string, x: number, config: Record<string, unknown>) {
  return {
    id,
    definition_id: definitionId,
    definition_version: 1,
    config,
    layout: { x, y: 0 },
  };
}

/** A `debug.echo` node: it reads a `message` and emits `{echoed, received_at}`. */
function echoNode(id: Uuid, x: number, message = "") {
  return debugNode(id, "debug.echo", x, { message });
}

/** A `debug.relay` node: it takes an echo's output and emits a plain `message`. */
function relayNode(id: Uuid, x: number) {
  return debugNode(id, "debug.relay", x, {});
}

/** Bind one of a relay's required inputs to the same-named field of an echo's output. */
function relayInput(relayId: Uuid, echoId: Uuid, field: string): Binding {
  return {
    target_node_id: relayId,
    target_field: field,
    source: { kind: "node_output", node_id: echoId, port: "out", field_path: [field] },
  };
}

/** A starter template: an `id` (its copy is keyed on it) and the draft graph it seeds. */
export interface WorkflowTemplate {
  id: string;
  graph: WorkflowGraph;
}

const STARTER_NODE_ID = "a1111111-1111-4111-8111-111111111111";

const SEQUENCE_NODE_A = "b2222222-2222-4222-8222-222222222222";
const SEQUENCE_NODE_B = "c3333333-3333-4333-8333-333333333333";
const SEQUENCE_EDGE_ID = "d4444444-4444-4444-8444-444444444444";

/**
 * The templates offered in the create dialog, in the order they appear.
 *
 * `starter` is a single step to rename and wire up; `sequence` is an Echo already
 * connected to a Relay that reads its output, a starting point for a linear flow.
 * Both validate as they stand, so `sequence` publishes without an edit.
 */
export const WORKFLOW_TEMPLATES: readonly WorkflowTemplate[] = [
  {
    id: "starter",
    graph: {
      entry_node_id: STARTER_NODE_ID,
      nodes: [echoNode(STARTER_NODE_ID, 0, "Hello")],
      edges: [],
      bindings: [],
      scopes: [],
    },
  },
  {
    id: "sequence",
    graph: {
      entry_node_id: SEQUENCE_NODE_A,
      nodes: [echoNode(SEQUENCE_NODE_A, 0, "Hello"), relayNode(SEQUENCE_NODE_B, 280)],
      edges: [
        {
          id: SEQUENCE_EDGE_ID,
          source_node_id: SEQUENCE_NODE_A,
          source_port: "out",
          target_node_id: SEQUENCE_NODE_B,
          target_port: "in",
        },
      ],
      bindings: [
        relayInput(SEQUENCE_NODE_B, SEQUENCE_NODE_A, "echoed"),
        relayInput(SEQUENCE_NODE_B, SEQUENCE_NODE_A, "received_at"),
      ],
      scopes: [],
    },
  },
];
