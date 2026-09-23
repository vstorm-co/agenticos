/**
 * The starter workflow templates the create dialog offers (#1787).
 *
 * For v1 these are static, frontend-shipped `WorkflowGraph`s: "create from
 * template" seeds a brand-new workflow's *draft* graph with one of them, so the
 * reader lands on a canvas that already has a step or two rather than an empty
 * one. They are draft seeds, not published versions — the reader edits and
 * publishes from here — so they only have to parse as a `WorkflowGraph`, not pass
 * the publish-time validator.
 *
 * Everything is built on `debug.echo`, the one node #1786 ships; richer templates
 * arrive as #1789–#1792 populate the catalog. Each template's node ids are fixed
 * UUIDs: unique *within* a graph is all the model asks, and two workflows seeded
 * from the same template hold independent drafts, so reusing the ids across
 * workflows is harmless.
 *
 * A template is `{ id, graph }` only — its name and description are catalog copy
 * the dialog resolves as `pages.workflows.templates.<id>.name` / `.description`,
 * because a module constant has no translator to reach (see `.claude/rules/frontend.md`).
 */

import type { Uuid, WorkflowGraph } from "@/lib/workflows/types";

/** The node definition every v1 template is built from — the one node #1786 ships. */
const ECHO_DEFINITION_ID = "debug.echo";
const ECHO_DEFINITION_VERSION = 1;

/** A `debug.echo` node instance at a fixed canvas position. */
function echoNode(id: Uuid, x: number) {
  return {
    id,
    definition_id: ECHO_DEFINITION_ID,
    definition_version: ECHO_DEFINITION_VERSION,
    config: {},
    layout: { x, y: 0 },
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
 * `starter` is a single step to rename and wire up; `sequence` is two steps
 * already connected, a starting point for a linear flow.
 */
export const WORKFLOW_TEMPLATES: readonly WorkflowTemplate[] = [
  {
    id: "starter",
    graph: {
      entry_node_id: STARTER_NODE_ID,
      nodes: [echoNode(STARTER_NODE_ID, 0)],
      edges: [],
      bindings: [],
      scopes: [],
    },
  },
  {
    id: "sequence",
    graph: {
      entry_node_id: SEQUENCE_NODE_A,
      nodes: [echoNode(SEQUENCE_NODE_A, 0), echoNode(SEQUENCE_NODE_B, 280)],
      edges: [
        {
          id: SEQUENCE_EDGE_ID,
          source_node_id: SEQUENCE_NODE_A,
          source_port: "out",
          target_node_id: SEQUENCE_NODE_B,
          target_port: "in",
        },
      ],
      bindings: [],
      scopes: [],
    },
  },
];
