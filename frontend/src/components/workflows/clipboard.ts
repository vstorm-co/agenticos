import type { WorkflowClipboard } from "@/stores/workflow-editor-store";

/**
 * The copy/paste seam — the #1787 clipboard leaf fills this module.
 *
 * #1786's flat, uniform binding list makes the remap general rather than
 * per-node-kind: assign new ids to every copied node/edge/scope-boundary; for
 * each `Binding` remap `target_node_id`, and remap `NodeOutputRef.node_id` the
 * same way when it names a copied node (leave it alone otherwise); keep a
 * `ScopeBoundary` only when fully contained in the selection. This never
 * inspects a node's `config`, so a new node kind from #1789–#1792 needs no
 * clipboard change. The clipboard is keyed per organization and workflow (held
 * in the editor store's `clipboard`), never a module variable surviving remounts.
 */
export interface PasteResult {
  /** The remapped selection, with fresh ids, ready to merge into the graph. */
  clipboard: WorkflowClipboard;
  /** Old-id → new-id, so the caller can select what it just pasted. */
  idMap: Record<string, string>;
}

// TODO(#1787 clipboard leaf): implement `copySelection(...)` producing a
// `WorkflowClipboard` and `pasteClipboard(...)` producing a `PasteResult`.
