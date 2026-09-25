/**
 * Graph topology the rules run over — the client mirror of the structural parts
 * of `validate.py` that precede the rules: scope derivation, node→scope ownership,
 * Kahn's ordering and dominator sets.
 *
 * Like the backend, the mirror **derives** scopes from the graph's own edges
 * rather than trusting whatever `scopes` a draft carries — a freshly-edited graph's
 * client-held scopes are stale until the server recomputes them, so the mirror
 * recomputes them too. Every scope `derive_scopes` can produce sets
 * `exit_node_id = scope_node_id`; #1790's body-interior exit (`loop.yield`) is not
 * derivable from topology alone and is out of the mirror's scope, exactly as no
 * #1786 control node produces one.
 */

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
    map.set(node.id, index.get(definitionKey(node.definition_id, node.definition_version)) ?? null);
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
 * Forward BFS from `entryPort`'s targets, never re-entering `scopeNodeId` — the
 * analog of `_body_reachable_from`. Excluding the scope node (rather than
 * special-casing the exit port) is what stops the body from absorbing everything
 * downstream of the scope.
 */
function bodyReachableFrom(
  graph: WorkflowGraph,
  forward: Map<string, WorkflowEdge[]>,
  scopeNodeId: string,
  entryPort: string,
): Set<string> {
  const seen = new Set<string>();
  const queue: string[] = graph.edges
    .filter((edge) => edge.source_node_id === scopeNodeId && edge.source_port === entryPort)
    .map((edge) => edge.target_node_id);
  while (queue.length > 0) {
    const current = queue.shift() as string;
    if (seen.has(current) || current === scopeNodeId) continue;
    seen.add(current);
    for (const edge of forward.get(current) ?? []) {
      if (!seen.has(edge.target_node_id)) queue.push(edge.target_node_id);
    }
  }
  return seen;
}

/**
 * Recompute `scopes` from the graph's topology — the analog of `derive_scopes`.
 *
 * `body_node_ids` is the set reachable from the control node's first output port
 * without re-entering it. `exit_node_id` is always the control node itself, the
 * only value derivable without #1790's body-interior exit metadata.
 */
export function deriveScopes(graph: WorkflowGraph, definitions: DefinitionMap): ScopeBoundary[] {
  const forward = forwardEdges(graph);
  const scopes: ScopeBoundary[] = [];
  for (const node of graph.nodes) {
    const definition = definitionFor(definitions, node.id);
    if (definition === null || !ownsAScope(definition)) continue;
    const outputPorts = definition.ports.filter((port) => port.kind === "output");
    const [entry, exit] = outputPorts;
    if (entry === undefined || exit === undefined) continue;
    const entryPort = entry.id;
    const exitPort = exit.id;
    const body = bodyReachableFrom(graph, forward, node.id, entryPort);
    scopes.push({
      scope_node_id: node.id,
      body_node_ids: [...body],
      entry_port: entryPort,
      exit_node_id: node.id,
      exit_port: exitPort,
    });
  }
  return scopes;
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

/**
 * Iterative dominator sets over a topological order — the analog of `_dominators`.
 * `Dom(root) = {root}`; `Dom(n) = {n} ∪ ⋂ Dom(p)` over resolved predecessors.
 */
export function dominators(
  order: readonly string[],
  predecessors: Map<string, Set<string>>,
  root: string,
): Map<string, Set<string>> {
  const dom = new Map<string, Set<string>>([[root, new Set([root])]]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const nodeId of order) {
      if (nodeId === root) continue;
      const preds = [...(predecessors.get(nodeId) ?? [])].filter((p) => dom.has(p));
      if (preds.length === 0) continue;
      const intersection = intersectAll(preds.map((p) => dom.get(p) as Set<string>));
      intersection.add(nodeId);
      if (!sameSet(dom.get(nodeId), intersection)) {
        dom.set(nodeId, intersection);
        changed = true;
      }
    }
  }
  return dom;
}

function intersectAll(sets: Set<string>[]): Set<string> {
  const [first, ...rest] = sets;
  let result = new Set(first);
  for (const set of rest) result = new Set([...result].filter((value) => set.has(value)));
  return result;
}

function sameSet(left: Set<string> | undefined, right: Set<string>): boolean {
  return (
    left !== undefined && left.size === right.size && [...right].every((value) => left.has(value))
  );
}

/**
 * Dominator sets for the whole graph — outer nodes rooted at the entry, plus each
 * scope body rooted at its control node. The analog of `_all_dominators`. Empty
 * when the outer graph has a cycle or the entry is not a real node, because there
 * is then no order to compute over.
 */
export function allDominators(
  graph: WorkflowGraph,
  scopes: readonly ScopeBoundary[],
  outerPredecessors: Map<string, Set<string>>,
  outerOrder: string[] | null,
): Map<string, Set<string>> {
  if (outerOrder === null || !nodeIds(graph).has(graph.entry_node_id)) return new Map();
  const result = dominators(outerOrder, outerPredecessors, graph.entry_node_id);

  for (const scope of scopes) {
    const body = new Set(scope.body_node_ids);
    const bodyEdges = graph.edges.filter(
      (edge) => body.has(edge.source_node_id) && body.has(edge.target_node_id),
    );
    const { predecessors, order, cyclic } = kahn(scope.body_node_ids, bodyEdges);
    if (cyclic.size > 0) continue;
    const entryTargets = graph.edges
      .filter(
        (edge) =>
          edge.source_node_id === scope.scope_node_id && edge.source_port === scope.entry_port,
      )
      .map((edge) => edge.target_node_id);
    for (const nodeId of entryTargets) {
      const preds = predecessors.get(nodeId) ?? new Set<string>();
      preds.add(scope.scope_node_id);
      predecessors.set(nodeId, preds);
    }
    const bodyDominators = dominators(
      [scope.scope_node_id, ...order],
      predecessors,
      scope.scope_node_id,
    );
    for (const [nodeId, doms] of bodyDominators) {
      if (body.has(nodeId)) result.set(nodeId, doms);
    }
  }
  return result;
}
