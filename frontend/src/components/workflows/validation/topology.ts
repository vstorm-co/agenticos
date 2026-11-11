/**
 * Graph topology the rules run over — the client mirror of the structural parts
 * of `validate.py` that precede the rules: scope derivation, node→scope ownership
 * and Kahn's ordering.
 *
 * Like the backend, the mirror **derives** scopes from the loop each step names
 * (`scope_id`) rather than trusting whatever `scopes` a draft carries — a
 * freshly-edited graph's client-held scopes are stale until the server recomputes
 * them, so the mirror recomputes them too. Every scope `derive_scopes` produces sets
 * `exit_node_id = scope_node_id`.
 */

import { effectiveDefinition } from "@/lib/workflows/ports";
import { entryNodes } from "@/lib/workflows/triggers";
import type {
  NodeCatalog,
  NodeDefinition,
  ScopeBoundary,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

/** A resolved definition per node id, or null where the catalog has no such version. */
export type DefinitionMap = Map<string, NodeDefinition | null>;

function definitionKey(id: string, version: number): string {
  return `${id}\u0000${version}`;
}

/** Index a catalog by `(id, version)` for O(1) lookup. */
export function indexCatalog(catalog: NodeCatalog): Map<string, NodeDefinition> {
  const index = new Map<string, NodeDefinition>();
  for (const definition of catalog.items) {
    index.set(definitionKey(definition.id, definition.version), definition);
  }
  return index;
}

/** Resolve every node's `(definition_id, definition_version)` against the catalog. */
export function resolveDefinitions(graph: WorkflowGraph, catalog: NodeCatalog): DefinitionMap {
  const index = indexCatalog(catalog);
  const map: DefinitionMap = new Map();
  for (const node of graph.nodes) {
    const definition = index.get(definitionKey(node.definition_id, node.definition_version));
    map.set(node.id, definition === undefined ? null : effectiveDefinition(node, definition));
  }
  return map;
}

/**
 * The definition resolved for a node, or null — for one, or for a node not in the
 * map at all. Centralized so the "not in the map" fallback is expressed and tested
 * once, rather than at every call site as a `?? null` whose fallback a real graph
 * (every rule runs after the dangling-reference check) can never take.
 */
export function definitionFor(definitions: DefinitionMap, nodeId: string): NodeDefinition | null {
  return definitions.get(nodeId) ?? null;
}

/** The set of node ids actually present in the graph. */
export function nodeIds(graph: WorkflowGraph): Set<string> {
  return new Set(graph.nodes.map((node) => node.id));
}

/**
 * Steps switched off with no edge at all: parked beside the graph, never run. They
 * need not be reachable, and one may be a step that decides the way; rule 13 still
 * refuses a read of one. A trigger is never one: a run
 * can start at it wired or not. Mirrors `set_aside` in
 * `backend/app/workflows/graph/validate.py`.
 */
export function setAside(graph: WorkflowGraph): Set<string> {
  const wired = new Set(graph.edges.flatMap((e) => [e.source_node_id, e.target_node_id]));
  for (const entry of entryNodes(graph)) wired.add(entry.id);
  return new Set(
    graph.nodes.filter((n) => n.disabled === true && !wired.has(n.id)).map((n) => n.id),
  );
}

/** Outgoing edges keyed by source node id. */
export function forwardEdges(graph: WorkflowGraph): Map<string, WorkflowEdge[]> {
  const adjacency = new Map<string, WorkflowEdge[]>();
  for (const edge of graph.edges) {
    const list = adjacency.get(edge.source_node_id);
    if (list === undefined) adjacency.set(edge.source_node_id, [edge]);
    else list.push(edge);
  }
  return adjacency;
}

/**
 * Whether a control node owns a body, as opposed to a plain branch — the analog of
 * `_owns_a_scope`. Only a `control.*`-namespaced control node does; `logic.if`
 * branches without owning one.
 */
function ownsAScope(definition: NodeDefinition): boolean {
  return definition.kind === "control" && definition.id.startsWith("control.");
}

/**
 * Recompute `scopes` from the loop each step names - the analog of `derive_scopes`.
 *
 * `body_node_ids` is every step whose chain of `scope_id`s leads to the control node,
 * nested bodies included; wires play no part, so removing one never moves a step out
 * of its loop. `exit_node_id` is the control node itself, leaving through its first
 * output port.
 */
export function deriveScopes(graph: WorkflowGraph, definitions: DefinitionMap): ScopeBoundary[] {
  const children = new Map<string, string[]>();
  for (const node of graph.nodes) {
    if (node.scope_id == null) continue;
    const list = children.get(node.scope_id);
    if (list === undefined) children.set(node.scope_id, [node.id]);
    else list.push(node.id);
  }
  const scopes: ScopeBoundary[] = [];
  for (const node of graph.nodes) {
    const definition = definitionFor(definitions, node.id);
    if (definition === null || !ownsAScope(definition)) continue;
    const exit = definition.ports.find((port) => port.kind === "output");
    if (exit === undefined) continue;
    scopes.push({
      scope_node_id: node.id,
      body_node_ids: [...descendants(node.id, children)],
      exit_node_id: node.id,
      exit_port: exit.id,
    });
  }
  return scopes;
}

/** Every step inside `scopeNodeId`, nested loops' steps included; never the loop itself. */
function descendants(scopeNodeId: string, children: Map<string, string[]>): Set<string> {
  const seen = new Set<string>();
  const queue = [...(children.get(scopeNodeId) ?? [])];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    if (seen.has(current) || current === scopeNodeId) continue;
    seen.add(current);
    queue.push(...(children.get(current) ?? []));
  }
  return seen;
}

/** The `loop.item` step a loop's body starts at, or null when the body has none. */
export function loopItemOf(graph: WorkflowGraph, loopId: string): string | null {
  return (
    graph.nodes.find((node) => node.scope_id === loopId && node.definition_id === "loop.item")
      ?.id ?? null
  );
}

/**
 * Which scope owns each node, resolving to the innermost — the analog of
 * `_node_scope_map`. Nested bodies overlap (an outer body BFS walks through a
 * nested loop into its body too), so the smallest containing body wins.
 */
export function nodeScopeMap(scopes: readonly ScopeBoundary[]): Map<string, string> {
  const owner = new Map<string, string>();
  const ownerBodySize = new Map<string, number>();
  for (const scope of scopes) {
    const bodySize = scope.body_node_ids.length;
    for (const nodeId of scope.body_node_ids) {
      const current = ownerBodySize.get(nodeId);
      if (current === undefined || bodySize < current) {
        owner.set(nodeId, scope.scope_node_id);
        ownerBodySize.set(nodeId, bodySize);
      }
    }
  }
  return owner;
}

/** The result of Kahn's algorithm over one node set: predecessors, order, and any cycle. */
export interface KahnResult {
  predecessors: Map<string, Set<string>>;
  order: string[];
  cyclic: Set<string>;
}

/**
 * Kahn's topological sort over a pre-filtered node set — the analog of `_kahn`.
 * An edge whose endpoint is outside the set is ignored, so it cannot corrupt the
 * in-degree bookkeeping of the nodes actually being ordered.
 */
export function kahn(nodes: readonly string[], edges: readonly WorkflowEdge[]): KahnResult {
  const predecessors = new Map<string, Set<string>>();
  const successors = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const nodeId of nodes) {
    predecessors.set(nodeId, new Set());
    successors.set(nodeId, []);
    inDegree.set(nodeId, 0);
  }
  for (const edge of edges) {
    if (!inDegree.has(edge.source_node_id) || !inDegree.has(edge.target_node_id)) continue;
    (successors.get(edge.source_node_id) as string[]).push(edge.target_node_id);
    (predecessors.get(edge.target_node_id) as Set<string>).add(edge.source_node_id);
    inDegree.set(edge.target_node_id, (inDegree.get(edge.target_node_id) as number) + 1);
  }

  const queue: string[] = [];
  for (const [nodeId, degree] of inDegree) {
    if (degree === 0) queue.push(nodeId);
  }
  const order: string[] = [];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    order.push(current);
    for (const successor of successors.get(current) as string[]) {
      const remaining = (inDegree.get(successor) as number) - 1;
      inDegree.set(successor, remaining);
      if (remaining === 0) queue.push(successor);
    }
  }
  const ordered = new Set(order);
  const cyclic = new Set(nodes.filter((nodeId) => !ordered.has(nodeId)));
  return { predecessors, order, cyclic };
}
