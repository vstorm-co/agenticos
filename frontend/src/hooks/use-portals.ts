"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchPortalCatalog } from "@/lib/portals-api";
import { qk } from "@/lib/query-keys";
import type { PortalCatalogEntry } from "@/types/portals";
import { useMcpServers } from "./use-mcp-servers";

/**
 * The trigger-portals catalog, each entry carrying its org connection's state.
 *
 * Not cached indefinitely like the MCP catalog beside it: the entries are
 * hand-curated, but the connection state riding on them moves - an account is
 * connected, re-authorized, disabled - so the app-wide default staleness is the
 * right one here.
 */
export function usePortalCatalog() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.portals.catalog(),
    queryFn: fetchPortalCatalog,
  });
  return { portals: data ?? [], isLoading, error };
}

/**
 * Which action a portal card offers, derived from its delivery and connection.
 *
 * `create` needs no account (a manual portal, whose relay the user runs) or a
 * working one whose grant covers the scopes the portal needs; `connect` is the
 * first step for a portal nobody has connected - a webhook one to register the
 * hook, a polled one because the account *is* the delivery; `reauthorize` covers every state where a connection exists
 * but cannot register a webhook yet - a grant still awaiting consent, a disabled or
 * unreachable connection, or a grant that does not include the portal's
 * `webhook_admin_scopes` - all of which the same re-consent repairs.
 *
 * The state is the catalog's own (`connection_state`, resolved server-side), not a
 * join over the `mcp:manage`-gated connection listing: a Member or Operator whose
 * one run grant authorizes the create could not read that listing, so the join
 * showed them "connect", hid the connect control they may not use, and left no way
 * in at all.
 */
export type PortalAction = "create" | "connect" | "reauthorize";

export interface PortalWithState {
  portal: PortalCatalogEntry;
  action: PortalAction;
  /** The shared org connection's id, for creating triggers; null when none. */
  connectionId: string | null;
  /** The shared server's URL and name, for starting OAuth on the connection. */
  serverUrl: string | null;
  serverName: string | null;
}

function portalAction(portal: PortalCatalogEntry): PortalAction {
  // A *manual* portal wires its own delivery - the user runs the relay - so it
  // needs no account. A *polling* one is the opposite and the comment here used to
  // say otherwise: the platform reads the account, so without one there is nothing
  // to read, and offering Create let two Gmail triggers be made against a mailbox
  // nobody had connected. Neither could ever fire (#1068).
  if (portal.delivery === "manual") return "create";
  if (portal.connection_id === null) return "connect";
  // A grant still awaiting consent, disabled, or unreachable is not usable yet.
  if (portal.connection_state !== "connected") return "reauthorize";
  // Connected. A webhook portal still needs the scope that registers the hook; a
  // polled one asked for its read scopes at consent and holds them or does not,
  // which `connection_state` already answered.
  if (portal.delivery === "polling") return "create";
  return portal.connection_covers_webhook_scopes ? "create" : "reauthorize";
}

/**
 * The portal catalog with each card's action, plus what starting OAuth needs.
 *
 * The action and the connection id come off the catalog itself. `useMcpServers`
 * is joined only for the server URL and display name a *connect* needs to start
 * the generic OAuth flow - a management affordance, so the join failing for a
 * caller without `mcp:manage` costs them nothing they could use.
 */
export function usePortals() {
  const { portals, isLoading: catalogLoading, error } = usePortalCatalog();
  const { rows } = useMcpServers();

  const items = useMemo<PortalWithState[]>(
    () =>
      portals.map((portal) => {
        const row = portal.connection_catalog_key
          ? (rows.find((entry) => entry.entry?.key === portal.connection_catalog_key) ?? null)
          : null;
        return {
          portal,
          action: portalAction(portal),
          connectionId: portal.connection_id,
          serverUrl: row?.url ?? null,
          serverName: row?.entry?.name ?? row?.name ?? null,
        };
      }),
    [portals, rows],
  );

  return { items, isLoading: catalogLoading, error };
}
