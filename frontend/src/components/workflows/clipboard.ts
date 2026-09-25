import type {
  Binding,
  NodeOutputRef,
  NodePosition,
  ScopeBoundary,
  Uuid,
  WorkflowGraph,
} from "@/lib/workflows/types";
import type { EditorSelection, WorkflowClipboard } from "@/stores/workflow-editor-store";

/**
 * The copy/paste seam — the #1787 clipboard leaf fills this module.
 *
 * Re-derived, not ported. #1781's lab clipboard hard-codes which config fields
 * carry a binding per node kind and its `default` branch silently treats an
 * unknown kind as bindingless — a latent bug the moment a new node kind
 * (#1789–#1792) arrives. #1786's model removes the shape that bug needs:
 * bindings are one flat list keyed by `(target_node_id, target_field)`, and a
 * node-to-node reference is a `NodeOutputRef.node_id`, uniform across every node
 * kind. So the remap is general and never reads a node's `config`:
 *
 * - assign a fresh id to every copied node, edge and scope boundary;
 * - for each copied `Binding`, remap `target_node_id` (always — the binding
 *   belongs to a copied node), and remap a `NodeOutputRef.node_id` the same way
 *   **only** when it names a copied node; an external reference is left alone so
 *   the paste still reads from the original producer;
 * - keep a `ScopeBoundary` only when every node it names is in the selection.
 *
 * Because `config` is never inspected, a new node kind needs no change here. The
 * clip is held in the editor store's `clipboard`, keyed per organization and
 * workflow by the store's lifecycle (cleared on load/teardown, remounted per
 * workflow) — never a module-level variable that would survive a remount. This
 * module holds no state; it is pure functions over the graph and the clip.
 */
export interface PasteResult {
  /** The remapped selection, with fresh ids, ready to merge into the graph. */
  clipboard: WorkflowClipboard;
  /** Old-id → new-id, so the caller can select what it just pasted. */
  idMap: Record<Uuid, Uuid>;
}

/** A deep, detached copy — the clip must not alias the live graph, nor a paste the clip. */
function clone<T>(value: T): T {
  return structuredClone(value);
}

/**
 * The clip for a selection, or `null` when no node is selected.
 *
 * Copies the selected nodes, the edges induced among them (both ends selected —
 * an edge with a loose end could not be pasted), the bindings those nodes are
 * the target of, and any scope boundary fully contained in the selection. Ids
 * are preserved as-is; {@link pasteClipboard} re-ids at paste time. Edge
 * selection (`selection.edgeIds`) does not widen the copy: an induced edge is
 * copied whether or not it was clicked, and a selected edge to an uncopied node
 * cannot travel.
 */
export function copySelection(
  graph: WorkflowGraph,
  selection: EditorSelection,
): WorkflowClipboard | null {
  const selected = new Set<Uuid>(selection.nodeIds);
  if (selected.size === 0) return null;

  const nodes = graph.nodes.filter((node) => selected.has(node.id));
  const edges = graph.edges.filter(
    (edge) => selected.has(edge.source_node_id) && selected.has(edge.target_node_id),
  );
  const bindings = graph.bindings.filter((binding) => selected.has(binding.target_node_id));
  // `graph.scopes` is server-derived (`derive_scopes` recomputes it at every draft
  // save and publish) and never client-authored on an edit, so copying and pasting
  // a contained scope is effectively inert: whatever travels here is overwritten the
  // next time the server re-derives it. It is kept for shape completeness and is
  // harmless — the paste re-ids it, and a stale or absent scope simply gets replaced.
  const scopes = graph.scopes.filter((scope) => scopeContained(scope, selected));

  return clone({ nodes, edges, bindings, scopes });
}

/** Whether every node a scope boundary names — owner, exit and body — is in the selection. */
function scopeContained(scope: ScopeBoundary, selected: ReadonlySet<Uuid>): boolean {
  return (
    selected.has(scope.scope_node_id) &&
    selected.has(scope.exit_node_id) &&
    scope.body_node_ids.every((id) => selected.has(id))
  );
}

/**
 * A remapped copy of a clip, every id fresh, ready to merge into the graph.
 *
 * `newId` mints a fresh id per copied node and per copied edge; `offset` shifts
 * each pasted node's layout so a paste does not land exactly on its source. A
 * binding's `target_node_id` is always remapped (it names a copied node); its
 * source is remapped only for a `NodeOutputRef.node_id` that names a copied node
 * — an external producer is left untouched. Scope ids all remap, since a scope
 * is copied only when fully contained. `config` is never read.
 */
export function pasteClipboard(
  clipboard: WorkflowClipboard,
  newId: () => Uuid,
  offset: NodePosition = { x: 0, y: 0 },
): PasteResult {
  const source = clone(clipboard);

  const idMap: Record<Uuid, Uuid> = {};
  for (const node of source.nodes) idMap[node.id] = newId();

  const remapNode = (id: Uuid): Uuid => idMap[id] ?? id;

  const nodes = source.nodes.map((node) => ({
    ...node,
    id: remapNode(node.id),
    layout: { x: node.layout.x + offset.x, y: node.layout.y + offset.y },
  }));

  const edges = source.edges.map((edge) => ({
    ...edge,
    id: newId(),
    source_node_id: remapNode(edge.source_node_id),
    target_node_id: remapNode(edge.target_node_id),
  }));

  const bindings = source.bindings.map((binding) => ({
    ...binding,
    target_node_id: remapNode(binding.target_node_id),
    source: remapSource(binding, idMap),
  }));

  const scopes = source.scopes.map((scope) => ({
    ...scope,
    scope_node_id: remapNode(scope.scope_node_id),
    exit_node_id: remapNode(scope.exit_node_id),
    body_node_ids: scope.body_node_ids.map(remapNode),
  }));

  return { clipboard: { nodes, edges, bindings, scopes }, idMap };
}

/**
 * A binding's source with any internal node reference remapped.
 *
 * Only a `NodeOutputRef` naming a copied node is rewritten; a reference to an
 * uncopied node, or a non-node source (file, table, literal), is returned
 * unchanged. This is the one place a source is inspected, and it reads only the
 * discriminant and `node_id`, never a node's `config`.
 */
function remapSource(binding: Binding, idMap: Record<Uuid, Uuid>): Binding["source"] {
  const { source } = binding;
  if (source.kind !== "node_output") return source;
  const remapped = idMap[source.node_id];
  if (remapped === undefined) return source;
  return { ...source, node_id: remapped } satisfies NodeOutputRef;
}
