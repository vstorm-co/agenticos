/**
 * What changed between two graphs - a published version and the draft, most
 * often - step by step: which were added, removed or changed, and in a changed
 * one, which of its fields. Moving a step on the canvas is not a change, and
 * neither is pinned test data, which a version never keeps.
 */

import type {
  Binding,
  NodeInstance,
  Uuid,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

export type StepChange = "added" | "removed" | "changed";

/** One field of a changed step: what it is, named the way the diff lists it. */
export type ChangedField =
  | { kind: "setting"; name: string }
  | { kind: "input"; name: string }
  | { kind: "name" | "note" | "switchedOff" | "version" | "whenItFails" };

export interface StepDiff {
  change: StepChange;
  /** For a changed step, what changed in it; empty for an added or removed one. */
  fields: ChangedField[];
}

export interface GraphDiff {
  /** Every step that differs, by id; a step absent here is the same in both. */
  steps: Map<Uuid, StepDiff>;
  /** The connections only the second graph has, and only the first. */
  edgesAdded: number;
  edgesRemoved: number;
  /** Both graphs at once - the second, and what only the first had - to draw. */
  union: WorkflowGraph;
}

/** A value as text that does not depend on the order its keys were written in. */
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a < b ? -1 : 1,
    );
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "undefined";
}

function same(a: unknown, b: unknown): boolean {
  return stable(a) === stable(b);
}

function bindingsOf(graph: WorkflowGraph, nodeId: Uuid): Map<string, Binding> {
  return new Map(
    graph.bindings
      .filter((binding) => binding.target_node_id === nodeId)
      .map((binding) => [binding.target_field, binding]),
  );
}

function fieldsChanged(
  before: NodeInstance,
  after: NodeInstance,
  bound: [Map<string, Binding>, Map<string, Binding>],
): ChangedField[] {
  const fields: ChangedField[] = [];
  if (before.definition_version !== after.definition_version) fields.push({ kind: "version" });
  if ((before.label ?? null) !== (after.label ?? null)) fields.push({ kind: "name" });
  if ((before.notes ?? null) !== (after.notes ?? null)) fields.push({ kind: "note" });
  if (Boolean(before.disabled) !== Boolean(after.disabled)) fields.push({ kind: "switchedOff" });
  if (!same(before.policy ?? null, after.policy ?? null)) fields.push({ kind: "whenItFails" });
  const settings = new Set([...Object.keys(before.config), ...Object.keys(after.config)]);
  for (const name of [...settings].sort()) {
    if (!same(before.config[name], after.config[name])) fields.push({ kind: "setting", name });
  }
  const [was, now] = bound;
  const inputs = new Set([...was.keys(), ...now.keys()]);
  for (const name of [...inputs].sort()) {
    if (!same(was.get(name)?.source, now.get(name)?.source)) fields.push({ kind: "input", name });
  }
  return fields;
}

/** How far apart two cards have to be not to cover each other. */
const CARD_WIDTH = 240;
const CARD_HEIGHT = 80;
const SHIFT = 120;

/**
 * A removed step where it stood, or below it when a step of the draft stands
 * there now - the two would otherwise be drawn one over the other.
 */
function besideTheDraft(node: NodeInstance, taken: NodeInstance[]): NodeInstance {
  const { x } = node.layout;
  let { y } = node.layout;
  while (
    taken.some(
      (other) =>
        Math.abs(other.layout.x - x) < CARD_WIDTH && Math.abs(other.layout.y - y) < CARD_HEIGHT,
    )
  ) {
    y += SHIFT;
  }
  return y === node.layout.y ? node : { ...node, layout: { x, y } };
}

function edgeKey(edge: WorkflowEdge): string {
  return `${edge.source_node_id}:${edge.source_port}>${edge.target_node_id}:${edge.target_port}`;
}

/** How `after` differs from `before`. */
export function diffGraphs(before: WorkflowGraph, after: WorkflowGraph): GraphDiff {
  const earlier = new Map(before.nodes.map((node) => [node.id, node]));
  const later = new Map(after.nodes.map((node) => [node.id, node]));
  const steps = new Map<Uuid, StepDiff>();
  for (const node of after.nodes) {
    const was = earlier.get(node.id);
    if (was === undefined) {
      steps.set(node.id, { change: "added", fields: [] });
      continue;
    }
    const fields = fieldsChanged(was, node, [
      bindingsOf(before, node.id),
      bindingsOf(after, node.id),
    ]);
    if (fields.length > 0) steps.set(node.id, { change: "changed", fields });
  }
  const removed = before.nodes.filter((node) => !later.has(node.id));
  for (const node of removed) steps.set(node.id, { change: "removed", fields: [] });

  const beforeEdges = new Set(before.edges.map(edgeKey));
  const afterEdges = new Set(after.edges.map(edgeKey));
  const goneEdges = before.edges.filter((edge) => !afterEdges.has(edgeKey(edge)));
  return {
    steps,
    edgesAdded: after.edges.filter((edge) => !beforeEdges.has(edgeKey(edge))).length,
    edgesRemoved: goneEdges.length,
    union: {
      ...after,
      nodes: removed.reduce<NodeInstance[]>(
        (placed, node) => [...placed, besideTheDraft(node, placed)],
        [...after.nodes],
      ),
      edges: [...after.edges, ...goneEdges],
      bindings: after.bindings,
    },
  };
}
