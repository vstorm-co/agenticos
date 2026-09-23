import type { NodeDefinition } from "@/lib/workflows/types";

/**
 * The `DataTransfer` type the palette writes a dragged node under, and the seam
 * the canvas leaf reads it back from in its `onDrop`.
 *
 * A private application MIME type, not `text/plain`, so a drop that originated
 * anywhere other than the palette carries no value under it and is ignored
 * rather than mistaken for a node.
 */
export const NODE_DRAG_MIME = "application/x-agenticos-workflow-node";

/**
 * Serialize a catalog entry onto a drag's `DataTransfer` on drag start.
 *
 * The palette owns the payload format; the canvas leaf's drop handler reads it
 * with {@link readNodeDragData}, resolves the drop point to graph coordinates it
 * alone can compute, and calls the store's `addNode`. The whole definition rides
 * along so the drop side needs no second catalog lookup.
 */
export function writeNodeDragData(dataTransfer: DataTransfer, definition: NodeDefinition): void {
  dataTransfer.setData(NODE_DRAG_MIME, JSON.stringify(definition));
  dataTransfer.effectAllowed = "copy";
}

/**
 * Parse the catalog entry the palette wrote, or `null` when the drag carries
 * none (a drop from outside the palette) or a malformed payload. The canvas
 * leaf's `onDrop` treats `null` as "not a palette drop" and does nothing.
 */
export function readNodeDragData(dataTransfer: DataTransfer): NodeDefinition | null {
  const raw = dataTransfer.getData(NODE_DRAG_MIME);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as NodeDefinition;
  } catch {
    return null;
  }
}
