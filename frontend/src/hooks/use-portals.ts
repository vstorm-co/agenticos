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
 * `create` needs no account (a manual/polling portal) or a working one; `connect`
 * is the first step for an auto-webhook portal nobody has connected; `reauthorize`
 * covers every state where a connection exists but cannot register a webhook yet -
 * an OAuth grant still awaiting consent, a disabled or unreachable connection -
 * all of which the same re-consent repairs.
 *
 * The scope-level question the design imagined - "connected, but is the
 * webhook-admin scope granted?" - is not answerable from the frontend: neither the
 * connection's `granted_scopes` nor a portal's required scopes are exposed by the
 * API. The OAuth authorization state (`needs-authorization`) is the closest signal
 * the contract offers and stands in for it here.
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

function portalAction(
  portal: PortalCatalogEntry,
  connection: McpConnectionRecord | null,
): PortalAction {
  // Manual and polling portals wire their own delivery, so no account is needed.
  if (portal.delivery !== "auto_webhook") return "create";
  if (connection === null) return "connect";
  return connectionState(connection) === "connected" ? "create" : "reauthorize";
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
        const connection = row?.organization ?? row?.personal ?? null;
        return {
          portal,
          action: portalAction(portal, connection),
          connection,
          serverUrl: row?.url ?? null,
          serverName: row?.entry?.name ?? row?.name ?? null,
        };
      }),
    [portals, rows],
  );

  return { items, isLoading: catalogLoading || serversLoading, error };
}
