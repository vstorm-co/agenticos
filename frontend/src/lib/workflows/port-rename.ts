import { AUTHOR_NAMED_PORTS, ERROR_PORT, routesErrors } from "./ports";
import type { BindingSource, NodeInstance, Uuid, WorkflowGraph } from "./types";

/** An author-named output port that kept its place in the list but got a new name. */
export interface PortRename {
  from: string;
  to: string;
}

function keysOf(entries: unknown[], key: string): unknown[] {
  return entries.map((entry) =>
    typeof entry === "object" && entry !== null
      ? (entry as Record<string, unknown>)[key]
      : undefined,
  );
}

/** Every output port name of the step that its edges, bindings or quick log still read. */
function readPorts(graph: WorkflowGraph, nodeId: Uuid): Set<string> {
  const names = new Set<string>();
  for (const edge of graph.edges) {
    if (edge.source_node_id === nodeId) names.add(edge.source_port);
  }
  const addRef = (ref: { node_id: Uuid; port: string }) => {
    if (ref.node_id === nodeId) names.add(ref.port);
  };
  for (const { source } of graph.bindings) {
    if (source.kind === "node_output") addRef(source);
    if (source.kind === "template") {
      for (const part of source.parts) if (typeof part !== "string") addRef(part);
    }
  }
  for (const port of graph.nodes.find((node) => node.id === nodeId)?.quick_log?.outputs ?? []) {
    names.add(port);
  }
  return names;
}

/**
 * The one port an edit to a step's config renamed, or null. Only a single entry whose
 * name changed in a list of the same length counts - a reorder, an insert, a delete or
 * two changes could each be a different step's intent, so nothing is carried for them -
 * and only to a name the step could own: not blank, not another entry's, not a port it
 * has anyway (`error` when it routes its errors, `unsure` on a classifier with a minimum).
 *
 * Every keystroke is an edit, so a name cleared and retyped (`big`, `bi`, `b`, blank, `l`)
 * or passing through another rule's name leaves the entry's old name blank or duplicated.
 * Then the rename continues from the one port name `graph` still reads on this step that
 * is no longer one of its ports; with none or several such names nothing is carried.
 */
export function portRename(
  before: NodeInstance,
  nextConfig: Record<string, unknown>,
  graph: WorkflowGraph,
): PortRename | null {
  const named = AUTHOR_NAMED_PORTS[before.definition_id];
  if (named === undefined) return null;
  const old = before.config[named.list];
  const next = nextConfig[named.list];
  if (!Array.isArray(old) || !Array.isArray(next) || old.length !== next.length) return null;
  const oldKeys = keysOf(old, named.key);
  const nextKeys = keysOf(next, named.key);
  const changed = oldKeys.flatMap((key, index) => (key === nextKeys[index] ? [] : [index]));
  const index = changed[0];
  if (changed.length !== 1 || index === undefined) return null;
  const to = nextKeys[index];
  if (typeof to !== "string" || to === "") return null;
  const taken = new Set<unknown>([...named.static, ...oldKeys]);
  if (routesErrors(before)) taken.add(ERROR_PORT);
  if (before.definition_id === "ai.classify" && typeof before.config.min_confidence === "number") {
    taken.add("unsure");
  }
  if (taken.has(to)) return null;
  const was = oldKeys[index];
  const uses = oldKeys.filter((key) => key === was).length;
  if (typeof was === "string" && was !== "" && uses === 1) return { from: was, to };
  const blank = was === undefined || was === "";
  if (!blank && !(typeof was === "string" && uses > 1)) return null;
  const orphans = [...readPorts(graph, before.id)].filter((port) => !taken.has(port));
  const from = orphans[0];
  return orphans.length === 1 && from !== undefined ? { from, to } : null;
}

function carriedSource(source: BindingSource, nodeId: Uuid, rename: PortRename): BindingSource {
  const moved = (ref: { node_id: Uuid; port: string }) =>
    ref.node_id === nodeId && ref.port === rename.from;
  if (source.kind === "node_output") {
    return moved(source) ? { ...source, port: rename.to } : source;
  }
  if (
    source.kind === "template" &&
    source.parts.some((part) => typeof part !== "string" && moved(part))
  ) {
    return {
      ...source,
      parts: source.parts.map((part) =>
        typeof part !== "string" && moved(part) ? { ...part, port: rename.to } : part,
      ),
    };
  }
  return source;
}

/**
 * `graph` with everything that read the step's `from` port reading `to`: its edges,
 * the bindings and template references that name it, and the step's own quick log.
 * Another step's port of the same name is untouched.
 */
export function carryPortRename(
  graph: WorkflowGraph,
  nodeId: Uuid,
  rename: PortRename,
): WorkflowGraph {
  const edges = graph.edges.map((edge) =>
    edge.source_node_id === nodeId && edge.source_port === rename.from
      ? { ...edge, source_port: rename.to }
      : edge,
  );
  const bindings = graph.bindings.map((binding) => {
    const source = carriedSource(binding.source, nodeId, rename);
    return source === binding.source ? binding : { ...binding, source };
  });
  const nodes = graph.nodes.map((node) => {
    const outputs = node.quick_log?.outputs;
    if (node.id !== nodeId || node.quick_log == null || outputs == null) return node;
    if (!outputs.includes(rename.from)) return node;
    return {
      ...node,
      quick_log: {
        ...node.quick_log,
        outputs: outputs.map((port) => (port === rename.from ? rename.to : port)),
      },
    };
  });
  return { ...graph, edges, bindings, nodes };
}
