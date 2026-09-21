import type { GraphEdge, GraphNode, NodeConfig, WorkflowGraph } from "./typed-graph";
import { collectIds } from "./typed-graph";

/**
 * Copy and paste over the typed graph, not over SDK nodes.
 *
 * The SDK ships no clipboard (the demo app's plugin is an Overflow premium
 * feature and is not in the npm package), and an SDK-level paste could not be
 * correct anyway: a foreach's body is not in the SDK's node data, and a binding
 * is a string the SDK does not parse. Pasting has to give every node, at every
 * depth, a new id, and rewrite every `{{ id.path }}` that names a copied node.
 */

export interface Clip {
  nodes: GraphNode[];
  /** Only edges with both ends inside the selection. */
  edges: GraphEdge[];
}

const BINDING = /\{\{\s*([\w-]+)/g;

/** Every node id a binding in `text` refers to. */
export function bindingTargets(text: string): string[] {
  return [...text.matchAll(BINDING)].map((match) => match[1] ?? "");
}

export function remapBindings(text: string, ids: ReadonlyMap<string, string>): string {
  return text.replace(/(\{\{\s*)([\w-]+)/g, (whole, open: string, id: string) => {
    const next = ids.get(id);
    return next === undefined ? whole : `${open}${next}`;
  });
}

function bindingsOf(config: NodeConfig): string[] {
  switch (config.kind) {
    case "agent":
      return [config.prompt];
    case "table_write":
      return config.mappings.map((row) => row.value);
    case "foreach":
      return [config.items];
    default:
      return [];
  }
}

function remapConfig(config: NodeConfig, ids: ReadonlyMap<string, string>): NodeConfig {
  switch (config.kind) {
    case "agent":
      return { ...config, prompt: remapBindings(config.prompt, ids) };
    case "table_write":
      return {
        ...config,
        mappings: config.mappings.map((row) => ({ ...row, value: remapBindings(row.value, ids) })),
      };
    case "foreach":
      return {
        ...config,
        items: remapBindings(config.items, ids),
        body: remapGraph(config.body, ids),
      };
    default:
      return config;
  }
}

function remapGraph(graph: WorkflowGraph, ids: ReadonlyMap<string, string>): WorkflowGraph {
  return {
    nodes: graph.nodes.map((node) => ({
      ...node,
      id: ids.get(node.id) ?? node.id,
      config: remapConfig(node.config, ids),
    })),
    edges: graph.edges.map((edge) => ({
      ...edge,
      source: ids.get(edge.source) ?? edge.source,
      target: ids.get(edge.target) ?? edge.target,
    })),
  };
}

export function copySelection(scope: WorkflowGraph, selected: ReadonlySet<string>): Clip {
  const nodes = structuredClone(scope.nodes.filter((node) => selected.has(node.id)));
  const kept = new Set(nodes.map((node) => node.id));
  const edges = structuredClone(
    scope.edges.filter((edge) => kept.has(edge.source) && kept.has(edge.target)),
  );
  return { nodes, edges };
}

export interface Pasted {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** old id -> new id, at every depth. */
  ids: Map<string, string>;
}

/**
 * The clip with every id replaced, at every nesting depth, and every binding that
 * named a copied node rewritten. Edges get new ids too. A binding to a node that
 * was not copied is left alone: it still names the original, which is what the
 * author of a paste inside the same scope wants, and `danglingBindings` is how a
 * paste into another workflow finds out it does not.
 */
export function pasteClip(
  clip: Clip,
  newId: () => string,
  offset: { x: number; y: number },
): Pasted {
  const ids = new Map<string, string>();
  for (const id of collectIds({ nodes: clip.nodes, edges: [] })) ids.set(id, newId());
  // Edge ids inside a body are scope-local and nothing refers to them, so they are kept.
  const remapped = remapGraph(structuredClone({ nodes: clip.nodes, edges: clip.edges }), ids);
  return {
    nodes: remapped.nodes.map((node) => ({
      ...node,
      position: { x: node.position.x + offset.x, y: node.position.y + offset.y },
    })),
    edges: remapped.edges.map((edge) => ({ ...edge, id: newId() })),
    ids,
  };
}

/** Bindings, at every depth, that name an id the graph does not contain. */
export function danglingBindings(
  graph: WorkflowGraph,
  known: ReadonlySet<string> = new Set(),
): string[] {
  const all = new Set([...collectIds(graph), ...known]);
  const missing: string[] = [];
  const walk = (scope: WorkflowGraph) => {
    for (const node of scope.nodes) {
      for (const text of bindingsOf(node.config)) {
        for (const target of bindingTargets(text)) {
          if (!all.has(target)) missing.push(`${node.id} -> ${target}`);
        }
      }
      if (node.config.kind === "foreach") walk(node.config.body);
    }
  };
  walk(graph);
  return missing;
}
