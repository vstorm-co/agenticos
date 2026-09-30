import type { Uuid, WorkflowGraph } from "@/lib/workflows/types";

/**
 * The scope filter that turns the flat `WorkflowGraph` into the subset one
 * `foreach` scope shows — a **view over the flat graph, not a nested document**
 * (the design's "Nested foreach editing: a view filter, not a nested document").
 *
 * `WorkflowGraph` is flat: nesting lives in `scopes: ScopeBoundary[]`, each a
 * `control.foreach` node plus the `body_node_ids` the server derives from edge
 * topology. The editor holds `scopePath` (foreach ids root-to-current) and draws
 * only the current scope's own nodes and edges, so entering or leaving a
 * `foreach` is a display change — nothing here mutates the graph, and autosave,
 * undo/redo and publish need no scope-aware branching.
 *
 * Kept pure and free of React so every branch is unit-testable with synthetic
 * graphs carrying scope boundaries (the shipped catalog has only `debug.echo`, so
 * no real `foreach` node exists yet — the tests build fixtures, as validation and
 * the palette scope filter do).
 */

/**
 * The scope currently in view — the last `foreach` id on the path, or `null` at
 * the root scope (an empty path). `null` is the graph-level scope, the nodes that
 * live in no `foreach` body.
 */
export function currentScopeId(scopePath: readonly Uuid[]): Uuid | null {
  return scopePath[scopePath.length - 1] ?? null;
}

/**
 * Each node's **innermost** owning scope, keyed by node id — the `scope_node_id`
 * of the boundary that contains it in the fewest members, or `null` when it is in
 * no boundary at all.
 *
 * `body_node_ids` is transitive: a node deep inside two nested loops is a member
 * of both bodies, so the boundaries containing a node form a chain and the
 * innermost is the one with the smallest body. That innermost scope is the one
 * whose view the node belongs to — a node directly in an outer loop shows there,
 * while the inner loop's own body shows only after entering it.
 */
export function owningScopeByNode(graph: WorkflowGraph): Map<Uuid, Uuid | null> {
  const owners = new Map<Uuid, Uuid | null>();
  for (const node of graph.nodes) {
    let owner: Uuid | null = null;
    let ownerSize = Number.POSITIVE_INFINITY;
    for (const scope of graph.scopes) {
      if (scope.body_node_ids.includes(node.id) && scope.body_node_ids.length < ownerSize) {
        owner = scope.scope_node_id;
        ownerSize = scope.body_node_ids.length;
      }
    }
    owners.set(node.id, owner);
  }
  return owners;
}

/**
 * The ids of the nodes visible in the scope named by `scopePath` — every node
 * whose innermost owning scope is the current one. At the root (empty path) this
 * is every node in no boundary, including a `foreach` node itself (a scope owner
 * is not a member of its own body).
 */
export function visibleNodeIds(graph: WorkflowGraph, scopePath: readonly Uuid[]): Set<Uuid> {
  const scopeId = currentScopeId(scopePath);
  const owners = owningScopeByNode(graph);
  const ids = new Set<Uuid>();
  for (const node of graph.nodes) {
    if (owners.get(node.id) === scopeId) ids.add(node.id);
  }
  return ids;
}

/**
 * The graph as the current scope renders it: nodes filtered to the visible set,
 * and edges kept only when **both** endpoints are visible — a scope's own edges.
 * The two boundary edges a `ScopeBoundary` declares cross scopes, so they belong
 * to neither the parent's nor the body's view and are left undrawn here.
 *
 * `bindings`, `scopes` and `entry_node_id` ride through unchanged: the canvas
 * projection reads only `nodes` and `edges`, and the store stays the one source
 * of truth for the whole graph.
 */
export function scopedGraph(graph: WorkflowGraph, scopePath: readonly Uuid[]): WorkflowGraph {
  const visible = visibleNodeIds(graph, scopePath);
  return {
    ...graph,
    nodes: graph.nodes.filter((node) => visible.has(node.id)),
    edges: graph.edges.filter(
      (edge) => visible.has(edge.source_node_id) && visible.has(edge.target_node_id),
    ),
  };
}
