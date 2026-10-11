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
 * `starter` and `sequence` are built on the two debug nodes #1786 ships,
 * `debug.echo` and `debug.relay`; the automations after them (#1953) on the real
 * catalog, with every resource a step pins - a table, a bot, an agent, the
 * people to tell - left for the builder to choose. Two
 * echoes cannot be joined - an edge needs both ports to carry the same shape and
 * Echo's output is not Echo's input - so a chain goes Echo → Relay. Each
 * template's node ids are fixed
 * UUIDs: unique *within* a graph is all the model asks, and two workflows seeded
 * from the same template hold independent drafts, so reusing the ids across
 * workflows is harmless.
 *
 * A template is `{ id, graph }` only — its name and description are catalog copy
 * the dialog resolves as `pages.workflows.templates.<id>.name` / `.description`,
 * because a module constant has no translator to reach (see `.claude/rules/frontend.md`).
 */

import type {
  Binding,
  NodeOutputRef,
  Uuid,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

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

/** A step of the real catalog, at a fixed position, with nothing pinned yet. */
function step(id: Uuid, definitionId: string, x: number, config: Record<string, unknown> = {}) {
  return { id, definition_id: definitionId, definition_version: 1, config, layout: { x, y: 0 } };
}

function wire(id: Uuid, source: Uuid, target: Uuid): WorkflowEdge {
  return {
    id,
    source_node_id: source,
    source_port: "out",
    target_node_id: target,
    target_port: "in",
  };
}

function read(node: Uuid, ...path: string[]): NodeOutputRef {
  return { kind: "node_output", node_id: node, port: "out", field_path: path };
}

const LEAD = {
  hook: "e5555555-5555-4555-8555-555555555501",
  save: "e5555555-5555-4555-8555-555555555502",
  answer: "e5555555-5555-4555-8555-555555555503",
};
const ALERT = {
  failed: "f6666666-6666-4666-8666-666666666601",
  post: "f6666666-6666-4666-8666-666666666602",
};
const DAILY = {
  clock: "a7777777-7777-4777-8777-777777777701",
  write: "a7777777-7777-4777-8777-777777777702",
  tell: "a7777777-7777-4777-8777-777777777703",
};

/**
 * Common automations: a webhook's leads saved to a table and answered, a
 * Slack message when another workflow fails, and a weekday summary an agent
 * writes and the team is told. Each opens with its pins to choose, which the
 * editor marks, and publishes once they are.
 */
export const AUTOMATION_TEMPLATES: readonly WorkflowTemplate[] = [
  {
    id: "leadIntake",
    graph: {
      entry_node_id: LEAD.hook,
      nodes: [
        step(LEAD.hook, "trigger.webhook", 0),
        step(LEAD.save, "table.record.create", 300),
        step(LEAD.answer, "webhook.respond", 600, { status_code: 201 }),
      ],
      edges: [
        wire("e5555555-5555-4555-8555-555555555511", LEAD.hook, LEAD.save),
        wire("e5555555-5555-4555-8555-555555555512", LEAD.save, LEAD.answer),
      ],
      bindings: [
        { target_node_id: LEAD.save, target_field: "values", source: read(LEAD.hook, "body") },
        { target_node_id: LEAD.answer, target_field: "body", source: read(LEAD.save, "record_id") },
      ],
      scopes: [],
    },
  },
  {
    id: "failureAlert",
    graph: {
      entry_node_id: ALERT.failed,
      nodes: [
        step(ALERT.failed, "trigger.workflow_failed", 0),
        step(ALERT.post, "slack.message.send", 300),
      ],
      edges: [wire("f6666666-6666-4666-8666-666666666611", ALERT.failed, ALERT.post)],
      bindings: [
        {
          target_node_id: ALERT.post,
          target_field: "text",
          source: {
            kind: "template",
            parts: [
              read(ALERT.failed, "workflow_name"),
              " failed at ", // i18n-exempt: message text the template sends, edited in the step
              read(ALERT.failed, "step_name"),
              ": ",
              read(ALERT.failed, "error", "message"),
            ],
          },
        },
      ],
      scopes: [],
    },
  },
  {
    id: "dailySummary",
    graph: {
      entry_node_id: DAILY.clock,
      nodes: [
        step(DAILY.clock, "trigger.schedule", 0, {
          schedule_kind: "cron",
          cron_expression: "0 8 * * 1-5",
          interval_seconds: null,
        }),
        step(DAILY.write, "agent.run", 300),
        // i18n-exempt: the subject the template sends, edited in the step
        step(DAILY.tell, "notification.send", 600, { subject: "Daily summary" }),
      ],
      edges: [
        wire("a7777777-7777-4777-8777-777777777711", DAILY.clock, DAILY.write),
        wire("a7777777-7777-4777-8777-777777777712", DAILY.write, DAILY.tell),
      ],
      bindings: [
        {
          target_node_id: DAILY.write,
          target_field: "prompt",
          source: {
            kind: "literal",
            // i18n-exempt: the prompt the template sends, edited in the step
            value: "Summarise yesterday's activity in five short bullet points.",
          },
        },
        { target_node_id: DAILY.tell, target_field: "message", source: read(DAILY.write, "text") },
      ],
      scopes: [],
    },
  },
];
