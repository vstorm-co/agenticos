"use client";

import { useActiveOrganizationRecovery } from "@/hooks/use-active-organization";

/**
 * Mounts the active-organization recovery, once, for the whole dashboard.
 *
 * It renders nothing. The reason it exists as a component at all is that the
 * recovery must run exactly once per failure: `usePermissions` is rendered by
 * the sidebar, the tab bar and most pages simultaneously, so hooking the
 * recovery to it directly would invalidate the query cache and toast once per
 * caller. A single element in the layout is the cheapest way to say "one of
 * these, here".
 */
export function ActiveOrgGuard() {
  useActiveOrganizationRecovery();
  return null;
}
