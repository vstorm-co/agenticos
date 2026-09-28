import type { NodeDefinition } from "@/lib/workflows/types";

/**
 * How deep a `foreach` body may nest in the palette's add path.
 *
 * #1786 gives a `foreach` body no interior exit — `loop.yield` is #1790 — so a
 * `foreach` opened inside another `foreach`'s body has no way to close and hand
 * control back to the outer loop yet. Until that lands, the palette caps foreach
 * nesting at the outermost level: a scope-owning node is offered at the root and
 * hidden once the current scope path has already reached this depth. Raise this
 * when #1790 registers a body-interior exit.
 */
export const MAX_SCOPE_NESTING_DEPTH = 1;

/**
 * Whether a catalog entry opens a scope body — the "boundary-shaped" kind.
 *
 * Structural, mirroring #1786's `_owns_a_scope`: a node owns a body exactly when
 * it is a `control.*`-namespaced control node (a looping construct like
 * `control.foreach`), classified by kind and id namespace rather than by a
 * bespoke denylist. A control node #1789–#1792 registers under `control.*` is
 * therefore classified without a palette change.
 */
export function ownsAScope(definition: NodeDefinition): boolean {
  return definition.kind === "control" && definition.id.startsWith("control.");
}

/**
 * Whether a catalog entry may be added into the scope the editor is viewing.
 *
 * `scopePath` is the store's foreach path, root-to-current (empty at the root).
 * A plain node is always addable. A scope-owning (boundary-shaped) node is
 * addable only while nesting has not yet reached {@link MAX_SCOPE_NESTING_DEPTH}
 * — the palette's structural guard over #1786's nested-scope rule, which both
 * hides boundary-shaped nodes inside a `foreach` body and blocks a second
 * `control.foreach` once the fan-out limit is hit.
 */
export function isAddableInScope(
  definition: NodeDefinition,
  scopePath: readonly string[],
): boolean {
  if (!ownsAScope(definition)) return true;
  return scopePath.length < MAX_SCOPE_NESTING_DEPTH;
}
