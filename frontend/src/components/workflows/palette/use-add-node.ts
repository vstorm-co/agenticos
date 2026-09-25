import type { NodeDefinition, NodePosition, Uuid } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/** How the palette adds a node to the working graph. */
export type AddNode = (definition: NodeDefinition, position: NodePosition) => Uuid;

/** The store's working-graph slice, the part the palette calls into. */
interface WorkingGraphSlice {
  addNode: AddNode;
}

/**
 * Subscribe to the store's `addNode`; the palette's click- and drop-add call it.
 *
 * The canvas leaf (#1787 canvas) owns the editor store's working-graph slice and
 * adds `addNode` to it, with this exact signature, in parallel with this leaf —
 * so it is not on the store's published type on this branch yet. The palette
 * reads it through this one documented view rather than declaring it on
 * `WorkflowEditorState`, which would force the store's own initializer to
 * provide `addNode` before the canvas leaf does and would collide with that
 * leaf's declaration on merge. The action exists at runtime whenever a node can
 * be added.
 */
export function useAddNode(): AddNode {
  return useWorkflowEditorStore((state) => (state as unknown as WorkingGraphSlice).addNode);
}
