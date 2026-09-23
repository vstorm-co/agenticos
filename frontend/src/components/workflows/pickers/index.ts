/**
 * Resource pickers seam — the #1787 pickers leaf fills this directory.
 *
 * Each follows `collection-picker.tsx`'s shape (disambiguating context, an
 * orphaned-reference state, a create-new escape hatch):
 * - agent + version (two-step; changing the agent clears the pinned version),
 * - collection (`collection-picker.tsx` reused as-is),
 * - table + column (against `TableIORef`, over `GET /api/v1/tables`),
 * - secret (the vault secret-selection pattern — an id, never a value).
 *
 * Empty until the leaf lands; the barrel exists so a leaf branch attaches here.
 */
export {};
