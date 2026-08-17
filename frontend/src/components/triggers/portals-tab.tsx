"use client";

import { PortalCatalog } from "@/components/triggers/portal-catalog";
import { useMcpOAuthOutcome, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

/**
 * The portals grid on the Activity page, beside the Scheduled tab.
 *
 * The surface owns the two decisions the grid should not make for itself: what
 * the caller may do (`agents:run` to create a trigger, `connections:manage` to
 * connect the organization's account), passed down so the cards hide the actions
 * rather than 403 on them. And it mounts `useMcpOAuthOutcome`, because connecting
 * an account leaves the app for the provider's consent screen and returns with
 * the result in the query string - the one place it can be announced.
 */
export function PortalsTab() {
  const { can } = usePermissions();
  useMcpOAuthOutcome();

  return (
    <PortalCatalog
      canRun={can(Perm.agentsRun)}
      canManageConnections={can(Perm.connectionsManage)}
    />
  );
}
