"use client";

import { AppConnections } from "@/components/connections/app-connections";
import { appConnectionScopeKey } from "@/lib/app-connection-journey";
import { useAuthStore, useOrgStore } from "@/stores";

/** Remount pending forms and callback state when either authenticated context changes. */
export function AppsTab() {
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  if (!userId) return null;
  const scope = { userId, orgId };
  return <AppConnections key={appConnectionScopeKey(scope)} scope={scope} />;
}
