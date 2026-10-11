import { HIDDEN_CATEGORIES } from "@/components/workflows/node-visuals";
import { isTrigger } from "@/lib/workflows/triggers";
import type { NodeDefinition } from "@/lib/workflows/types";

/**
 * How deep `control.foreach` bodies may nest - the backend's default
 * `WORKFLOW_FOREACH_MAX_DEPTH`, which publishing enforces. The palette stops
 * offering a loop once the scope being edited is already this deep, so an author
 * is not handed a step the next publish refuses.
 */
export const MAX_SCOPE_NESTING_DEPTH = 3;

/**
 * Whether a catalog entry opens a scope body - the "boundary-shaped" kind.
 *
 * Structural, mirroring the backend's `_owns_a_scope`: a node owns a body exactly
 * when it is a `control.*`-namespaced control node (a looping construct like
 * `control.foreach`), classified by kind and id namespace rather than by a
 * bespoke denylist.
 */
export function ownsAScope(definition: NodeDefinition): boolean {
  return definition.kind === "control" && definition.id.startsWith("control.");
}

/**
 * Whether a catalog entry may be added into the scope the editor is viewing.
 *
 * `scopePath` is the store's foreach path, root-to-current (empty at the root).
 * A loop's own `loop.item` and `loop.yield` exist only inside a body, so they are
 * offered only there; a loop is offered while nesting has not reached
 * {@link MAX_SCOPE_NESTING_DEPTH}; a trigger - where a run begins - only at the
 * top level; and the debug nodes are never offered to a builder at all.
 */
export function isAddableInScope(
  definition: NodeDefinition,
  scopePath: readonly string[],
): boolean {
  if (HIDDEN_CATEGORIES.has(definition.category)) return false;
  if (isTrigger(definition)) return scopePath.length === 0;
  if (definition.loop_body_only) return scopePath.length > 0;
  if (!ownsAScope(definition)) return true;
  return scopePath.length < MAX_SCOPE_NESTING_DEPTH;
}
