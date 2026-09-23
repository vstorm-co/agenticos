/**
 * The typed workflow graph the SDK evaluation round-trips through.
 *
 * This is a stand-in for the backend's workflow model, which does not exist yet
 * (#1782 onward). It is deliberately shaped like one: a discriminated union of
 * node configs, ids that bindings refer to, and a foreach that owns a nested
 * body graph. If the SDK is adopted, this file is replaced by the generated
 * types of the real API; the adapter is what the evaluation is measuring.
 */

/** A `{{ nodeId.path }}` reference to another node's output. */
export type Binding = string;

export interface GraphPoint {
  x: number;
  y: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
}

export interface TableColumnMapping {
  column: string;
  value: Binding;
}

export type TableWriteMode = "insert" | "upsert" | "update";

export type NodeConfig =
  | { kind: "start" }
  | { kind: "end" }
  | { kind: "agent"; agent_id: string; version_id: string; prompt: string }
  | {
      kind: "table_write";
      table_id: string;
      mode: TableWriteMode;
      key_column: string | null;
      batch_size: number;
      mappings: TableColumnMapping[];
      /** The SDK has no dict editor, so this is carried through untouched. */
      on_conflict: Record<string, string>;
    }
  | { kind: "foreach"; items: Binding; concurrency: number; body: WorkflowGraph };

export type NodeKind = NodeConfig["kind"];

export interface GraphNode {
  id: string;
  label: string;
  position: GraphPoint;
  config: NodeConfig;
}

export interface WorkflowGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const NODE_KINDS: readonly NodeKind[] = ["start", "agent", "table_write", "foreach", "end"];

/** Every id in a graph, at every nesting depth. */
export function collectIds(graph: WorkflowGraph): string[] {
  return graph.nodes.flatMap((node) => [
    node.id,
    ...(node.config.kind === "foreach" ? collectIds(node.config.body) : []),
  ]);
}

/** The scope a path of foreach node ids leads to. Throws when the path is stale. */
export function scopeAt(graph: WorkflowGraph, path: readonly string[]): WorkflowGraph {
  let scope = graph;
  for (const id of path) {
    const node = scope.nodes.find((candidate) => candidate.id === id);
    if (node?.config.kind !== "foreach") {
      throw new Error(`scope path names ${id}, which is not a foreach in this graph`);
    }
    scope = node.config.body;
  }
  return scope;
}

/** A copy of `graph` with the scope at `path` replaced. Everything else is shared. */
export function replaceScope(
  graph: WorkflowGraph,
  path: readonly string[],
  next: WorkflowGraph,
): WorkflowGraph {
  const [head, ...rest] = path;
  if (head === undefined) return next;
  if (!graph.nodes.some((node) => node.id === head)) {
    // `scopeAt` refuses the same path. Returning the graph unchanged here would let
    // a save report success with the edit dropped.
    throw new Error(`scope path names ${head}, which is not a foreach in this graph`);
  }
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      if (node.id !== head) return node;
      if (node.config.kind !== "foreach") {
        throw new Error(`scope path names ${head}, which is not a foreach in this graph`);
      }
      return {
        ...node,
        config: { ...node.config, body: replaceScope(node.config.body, rest, next) },
      };
    }),
  };
}

/** Deep equality for plain JSON-shaped graphs, key order ignored. */
export function graphsEqual(a: WorkflowGraph, b: WorkflowGraph): boolean {
  return canonical(a) === canonical(b);
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([x], [y]) => (x < y ? -1 : 1));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
