import { HIDDEN_CATEGORIES } from "@/components/workflows/node-visuals";
import { isTrigger } from "@/lib/workflows/triggers";
import type { NodeDefinition, NodeInstance } from "@/lib/workflows/types";

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
 * A loop's own `loop.item` and `loop.yield` are never offered: a new loop comes with
 * both, and a body holds exactly one of each; a loop is offered while nesting has not reached
 * {@link MAX_SCOPE_NESTING_DEPTH}; a trigger - where a run begins - only at the
 * top level; and the debug nodes are never offered to a builder at all.
 */
export function isAddableInScope(
  definition: NodeDefinition,
  scopePath: readonly string[],
): boolean {
  if (HIDDEN_CATEGORIES.has(definition.category)) return false;
  if (isTrigger(definition)) return scopePath.length === 0;
  if (definition.loop_body_only) return false;
  if (!ownsAScope(definition)) return true;
  return scopePath.length < MAX_SCOPE_NESTING_DEPTH;
}

/** Why a paste cannot land where the editor is: the palette would not offer it there. */
export type PasteRefusal = "trigger-in-loop" | "too-deep";

/**
 * Why pasting `nodes` into the scope at `scopePath` would build what the palette
 * refuses to, or null when it would not.
 *
 * Only the clip's roots - steps whose loop was not copied with them - land in the
 * scope being viewed, so only a root trigger is refused inside a body. A copied
 * loop brings its own nested loops, so the depth is the scope's plus the deepest
 * loop chain in the clip, as the server counts it at publish. A step whose
 * definition the catalog does not hold is left to validation.
 */
export function pasteRefusal(
  nodes: readonly NodeInstance[],
  catalog: readonly NodeDefinition[],
  scopePath: readonly string[],
): PasteRefusal | null {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const definitionOf = (node: NodeInstance) =>
    catalog.find(
      (item) => item.id === node.definition_id && item.version === node.definition_version,
    ) ?? null;
  const roots = nodes.filter((node) => node.scope_id == null || !byId.has(node.scope_id));
  if (scopePath.length > 0 && roots.some((node) => isTrigger(definitionOf(node)))) {
    return "trigger-in-loop";
  }
  // A draft can hold a loop named inside itself (validation reports it), so the
  // walk up stops at a step it has already passed.
  const loopDepth = (node: NodeInstance): number => {
    const passed = new Set<string>();
    let current: NodeInstance | undefined = node;
    while (current !== undefined && !passed.has(current.id)) {
      passed.add(current.id);
      current = current.scope_id == null ? undefined : byId.get(current.scope_id);
    }
    return passed.size;
  };
  const deepest = Math.max(
    0,
    ...nodes
      .filter((node) => {
        const definition = definitionOf(node);
        return definition !== null && ownsAScope(definition);
      })
      .map(loopDepth),
  );
  return scopePath.length + deepest > MAX_SCOPE_NESTING_DEPTH ? "too-deep" : null;
}
