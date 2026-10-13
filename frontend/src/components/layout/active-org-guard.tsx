"use client";

import { useActiveOrganizationRecovery } from "@/hooks/use-active-organization";
import { useOrganizations } from "@/hooks";

/**
 * Mounts the active organization, once, for the whole dashboard.
 *
 * It renders nothing. The reason it exists as a component at all is that the
 * recovery must run exactly once per failure: `usePermissions` is rendered by
 * the sidebar, the tab bar and most pages simultaneously, so hooking the
 * recovery to it directly would invalidate the query cache and toast once per
 * caller. A single element in the layout is the cheapest way to say "one of
 * these, here".
 *
 * `useOrganizations()` is mounted for its effect rather than its value, and it
 * is load-bearing. The recovery already holds `useOrganizationList`, so the list
 * itself was always fetched - what lives only in `useOrganizations` is the
 * effect that *chooses* one when nothing is chosen yet, and that used to be
 * mounted by the organization switcher standing permanently in the sidebar. The
 * switcher is a menu item now, and menu content mounts only when the menu is
 * opened, so `activeOrgId` stayed null until somebody clicked their own name.
 * Null is not an error anywhere: `apiClient` simply sends no
 * `X-Organization-Id`, and a hook keyed on it - `useMembers(activeOrgId ?? "")`
 * - asks for nothing at all. The sharing panel rendered without ever learning
 * who owned the resource, and the reusable integrations never arrived. No error,
 * no failed request, no empty state; the panels just looked like an organization
 * with nothing in it.
 */
export function ActiveOrgGuard() {
  useOrganizations();
  useActiveOrganizationRecovery();
  return null;
}
