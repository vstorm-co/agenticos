"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchPortalCatalog } from "@/lib/portals-api";
import { connectionState } from "@/lib/mcp-servers";
import { qk } from "@/lib/query-keys";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { PortalCatalogEntry } from "@/types/portals";
import { useMcpServers } from "./use-mcp-servers";

/**
 * The trigger-portals catalog.
 *
 * Cached indefinitely like the MCP catalog beside it: the list is hand-curated in
 * the backend and changes when it is redeployed, not while someone is reading it.
 */
export function usePortalCatalog() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.portals.catalog(),
    queryFn: fetchPortalCatalog,
    staleTime: Infinity,
  });
  return { portals: data ?? [], isLoading, error };
}

/**
 * Which action a portal card offers, derived from its delivery and connection.
 *
 * `create` needs no account (a manual/polling portal) or a working one whose grant
 * covers the webhook scope; `connect` is the first step for an auto-webhook portal
 * nobody has connected; `reauthorize` covers every state where a connection exists
 * but cannot register a webhook yet - a grant still awaiting consent, a disabled or
 * unreachable connection, or a connection whose `granted_scopes` do not include the
 * portal's `webhook_admin_scopes` - all of which the same re-consent repairs.
 *
 * That last case is the "connected but missing the webhook scope" state: the
 * account works, but its grant never included the scope the auto-registration
 * needs, so a create would fail at the provider. It is caught here rather than
 * discovered at trigger-create time.
 */
export type PortalAction = "create" | "connect" | "reauthorize";

export interface PortalWithState {
  portal: PortalCatalogEntry;
  action: PortalAction;
  /** The shared MCP connection, org preferred, or null when none is connected. */
  connection: McpConnectionRecord | null;
  /** The shared server's URL and name, for starting OAuth on the connection. */
  serverUrl: string | null;
  serverName: string | null;
}

/** Whether a grant covers every scope a portal's auto-registration requires. */
function coversScopes(granted: string[] | null, required: string[]): boolean {
  const have = new Set(granted ?? []);
  return required.every((scope) => have.has(scope));
}

function portalAction(
  portal: PortalCatalogEntry,
  connection: McpConnectionRecord | null,
  grantedScopes: string[] | null,
): PortalAction {
  // Manual and polling portals wire their own delivery, so no account is needed.
  if (portal.delivery !== "auto_webhook") return "create";
  if (connection === null) return "connect";
  // A grant still awaiting consent, disabled, or unreachable is not usable yet.
  if (connectionState(connection) !== "connected") return "reauthorize";
  // Connected, but the webhook scope decides create-vs-reauthorize.
  return coversScopes(grantedScopes, portal.webhook_admin_scopes) ? "create" : "reauthorize";
}

/**
 * The portal catalog joined with MCP connection state through
 * `connection_catalog_key`.
 *
 * The join reuses `useMcpServers`, so there is one connection system: a portal's
 * account is the same organization credential the agent's MCP tools bind, matched
 * on the shared catalog key. The organization connection is preferred over a
 * personal one because a trigger belongs to an agent, which runs on the
 * organization's credentials.
 */
export function usePortals() {
  const { portals, isLoading: catalogLoading, error } = usePortalCatalog();
  const { rows, isLoading: serversLoading } = useMcpServers();

  const items = useMemo<PortalWithState[]>(
    () =>
      portals.map((portal) => {
        const row = portal.connection_catalog_key
          ? (rows.find((entry) => entry.entry?.key === portal.connection_catalog_key) ?? null)
          : null;
        // The organization connection is what a trigger binds and where the OAuth
        // grant (and its `granted_scopes`) lives; a personal one is only a
        // fallback for reading state, never the account a webhook registers under.
        const orgConnection = row?.organization ?? null;
        const connection = orgConnection ?? row?.personal ?? null;
        return {
          portal,
          action: portalAction(portal, connection, orgConnection?.granted_scopes ?? null),
          connection,
          serverUrl: row?.url ?? null,
          serverName: row?.entry?.name ?? row?.name ?? null,
        };
      }),
    [portals, rows],
  );

  return { items, isLoading: catalogLoading || serversLoading, error };
}
