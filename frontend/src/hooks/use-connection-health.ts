"use client";

import { useQuery } from "@tanstack/react-query";

import { listAppConnections } from "@/lib/app-connections-api";
import { connectionHealthCounts } from "@/lib/connection-health";
import { listMcpConnections } from "@/lib/mcp-connections-api";
import { listOrgMcpConnections } from "@/lib/org-mcp-connections-api";
import { DASHBOARD_FRESHNESS } from "@/lib/query-freshness";
import { qk } from "@/lib/query-keys";
import { usePermissions } from "@/hooks/use-permissions";
import { useAuthStore, useOrgStore } from "@/stores";
import { Perm } from "@/types/permissions";

/**
 * How many connections need attention, for the sidebar badge and the
 * Connections tabs.
 *
 * Read-only, and deliberately no new endpoint: it reads the same three lists
 * the Connections page already fetches, under the same query keys, so opening
 * the page costs no second fetch. The organization's list is fetched only for
 * a caller holding `mcp:manage` - anyone else gets a 403 from it, which is a
 * truer thing to avoid than to show as an empty list - and the personal lists
 * are the ones every sidebar reader already has.
 */
export function useConnectionHealth() {
  const { can } = usePermissions();
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);

  const personal = useQuery({
    queryKey: qk.mcpConnections.list(),
    queryFn: listMcpConnections,
    ...DASHBOARD_FRESHNESS,
  });
  const organization = useQuery({
    queryKey: qk.mcpConnections.org(),
    queryFn: listOrgMcpConnections,
    enabled: can(Perm.mcpManage),
    ...DASHBOARD_FRESHNESS,
  });
  const apps = useQuery({
    queryKey: qk.appConnections.list(userId ?? "", orgId),
    queryFn: ({ signal }) => listAppConnections(signal),
    enabled: Boolean(userId),
    // Authorization is completed outside this tab; do not reuse a long freshness window.
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });

  return {
    ...connectionHealthCounts(personal.data ?? [], organization.data ?? [], apps.data ?? []),
    isLoading: personal.isLoading || organization.isLoading || apps.isLoading,
  };
}
