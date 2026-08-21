import type { OrgRole } from "@/types/organization";
import type { PermissionEntry, PermissionScope, RoleCatalog } from "@/types/permissions";

/**
 * `none < own < shared < team < all`, the order the backend's `Scope` defines.
 *
 * Ranked rather than compared as strings, for the reason `Scope` gives for
 * refusing string comparison on itself: alphabetically `all < none < own`, the
 * opposite of what the values mean.
 */
const SCOPE_RANK: Record<PermissionScope, number> = {
  none: 0,
  own: 1,
  shared: 2,
  team: 3,
  all: 4,
};

/** Whether `holder` holds everything `offered` does, at least as widely. */
function reaches(holder: Map<string, PermissionScope>, offered: PermissionEntry[]): boolean {
  return offered.every(
    (entry) => SCOPE_RANK[holder.get(entry.permission) ?? "none"] >= SCOPE_RANK[entry.scope],
  );
}

function held(entries: PermissionEntry[]): Map<string, PermissionScope> {
  return new Map(entries.map((entry) => [entry.permission, entry.scope]));
}

/**
 * The roles a member holding `role` may hand out, in catalog order.
 *
 * The client's copy of `app.core.permissions.assignable_roles`, and deliberately
 * the same arithmetic rather than a list: a role may be offered only when the
 * assigner's own authority *strictly* exceeds it - every permission the offered
 * role holds, held at least as widely by the assigner, and something the
 * assigner holds that it does not. So nobody is offered their own level, and
 * nobody at all is offered `owner`, because no role outranks it. Ownership moves
 * through transferring the organization.
 *
 * It is computed here rather than fetched because the catalog already carries
 * every role's permissions, so the answer needs no endpoint of its own - and
 * computing it from the same input the server uses is what keeps the two from
 * drifting. What the pickers offered before was every role in the catalog bar
 * `owner`, whoever was asking: an Admin was offered Admin and got a 403 after
 * typing the email address (#1028).
 *
 * An unknown role - or a catalog that has not answered yet - assigns nothing,
 * which is the same answer the server gives and the safe direction for a control
 * to be wrong in.
 */
export function assignableRoles(catalog: RoleCatalog | undefined, role: string): OrgRole[] {
  const mine = catalog?.roles.find((entry) => entry.name === role);
  if (catalog === undefined || mine === undefined) return [];
  const mineHeld = held(mine.permissions);
  return catalog.roles
    .filter(
      (entry) =>
        reaches(mineHeld, entry.permissions) && !reaches(held(entry.permissions), mine.permissions),
    )
    .map((entry) => entry.name);
}

/**
 * Which of `assignable` a picker should start on.
 *
 * `preferred` when it is on offer - so an Owner or an Admin still starts on
 * Member, as every invite dialog did before this - and otherwise the least
 * privileged role that is, which is the last in catalog order. A picker seeded
 * with a role its own list does not hold renders an empty trigger and submits a
 * value the server refuses.
 */
export function defaultAssignable(assignable: OrgRole[], preferred: OrgRole): OrgRole | "" {
  if (assignable.includes(preferred)) return preferred;
  return assignable.at(-1) ?? "";
}
